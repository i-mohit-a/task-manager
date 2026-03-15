import logging
import os
import re
from datetime import datetime
from pathlib import Path

from task_parser import parse_task_input  # noqa: F401 — re-exported for callers

logger = logging.getLogger(__name__)

_MISSING = object()

# ── module-level state ────────────────────────────────────────────────────────

_projects: list = []
_tasks: list = []
_archived_projects: list = []
_archived_tasks: list = []
_id_counter: int = 0
_id_map: dict = {}
_file_mtime: float = -1.0
_archive_mtime: float = -1.0

TASKS_FILE: Path = Path()
ARCHIVE_FILE: Path = Path()


def get_storage_path() -> Path:
    if os.environ.get("TASKMANAGER_DEV"):
        return Path(__file__).parent / "tasks.txt"
    app_support = Path.home() / "Library" / "Application Support" / "TaskManager"
    app_support.mkdir(parents=True, exist_ok=True)
    return app_support / "tasks.txt"


def _next_id() -> int:
    global _id_counter
    _id_counter += 1
    return _id_counter


# ── file format ───────────────────────────────────────────────────────────────

_TASK_RE = re.compile(r'^(\s*)- \[([ x])\] (.*)$')
_PROJECT_RE = re.compile(r'^# (.+?)(?:\s{2}# (.+))?$')
_CREATED_RE = re.compile(r'  # (\d{4}-\d{2}-\d{2}T[\d:.]+)$')
_COMPLETED_RE = re.compile(r'  ## (\d{4}-\d{2}-\d{2}T[\d:.]+)$')


def _parse_file(path: Path) -> tuple[list, list]:
    """Parse a tasks file into raw project/task dicts (IDs not yet assigned)."""
    projects = []
    tasks = []
    current_project = None
    parent_stack: list = []  # list of (level, task_dict)

    if not path.exists():
        return projects, tasks

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        # Project header: must start at column 0
        if line.startswith("# ") and not line.startswith("#  "):
            proj_match = _PROJECT_RE.match(line)
            if proj_match:
                name = proj_match.group(1).strip()
                created_at = proj_match.group(2) or datetime.now().isoformat()
                current_project = {
                    "id": None,
                    "name": name,
                    "created_at": created_at,
                    "archived": 0,
                    "position": len(projects),
                }
                projects.append(current_project)
                parent_stack = []
                continue

        # Task line
        task_match = _TASK_RE.match(line)
        if task_match and current_project is not None:
            indent = task_match.group(1)
            done_marker = task_match.group(2)
            rest = task_match.group(3)

            level = len(indent) // 2

            # Strip completed_at (##) then created_at (#) from end of line
            completed_at = None
            m = _COMPLETED_RE.search(rest)
            if m:
                completed_at = m.group(1)
                rest = rest[:m.start()]

            created_at = datetime.now().isoformat()
            m = _CREATED_RE.search(rest)
            if m:
                created_at = m.group(1)
                rest = rest[:m.start()]

            parsed = parse_task_input(rest.strip())

            # Determine parent by trimming stack to levels < current
            parent_stack = [(lvl, t) for lvl, t in parent_stack if lvl < level]
            parent_obj = parent_stack[-1][1] if parent_stack else None

            # Position among same-parent siblings already seen
            parent_obj_id_placeholder = id(parent_obj) if parent_obj else None
            siblings_count = sum(
                1 for t in tasks
                if id(t.get("_parent_obj")) == parent_obj_id_placeholder
                and t.get("_project_obj") is current_project
            )

            task = {
                "id": None,
                "project_id": None,      # resolved after ID assignment
                "parent_id": None,       # resolved after ID assignment
                "_project_obj": current_project,
                "_parent_obj": parent_obj,
                "title": parsed["title"],
                "priority": parsed["priority"],
                "effort_hours": parsed["effort_hours"],
                "start_date": parsed["start_date"],
                "due_date": parsed["due_date"],
                "level": level,
                "created_at": created_at,
                "completed_at": completed_at,
                "archived": 0,
                "position": siblings_count,
                "flags": ",".join(parsed["flags"]) if parsed["flags"] else "",
                "_cascade_ts": None,
            }
            tasks.append(task)
            parent_stack.append((level, task))

    return projects, tasks


def _resolve_file(path: Path) -> tuple[list, list]:
    """Parse file, assign IDs, resolve references. Returns (projects, tasks)."""
    projects, tasks = _parse_file(path)

    for p in projects:
        p["id"] = _next_id()
        _id_map[p["id"]] = p

    for t in tasks:
        t["id"] = _next_id()
        _id_map[t["id"]] = t

    for t in tasks:
        parent_obj = t.pop("_parent_obj", None)
        t["parent_id"] = parent_obj["id"] if parent_obj else None
        project_obj = t.pop("_project_obj", None)
        t["project_id"] = project_obj["id"] if project_obj else None

    return projects, tasks


# ── serialization ─────────────────────────────────────────────────────────────

def _serialize_tasks_dfs(tasks: list, parent_id=None) -> list[str]:
    """Serialize tasks in DFS order (parent before children)."""
    lines = []
    children = sorted(
        [t for t in tasks if t["parent_id"] == parent_id],
        key=lambda t: t["position"]
    )
    for task in children:
        indent = "  " * task["level"]
        done = "x" if task["completed_at"] else " "
        parts = [task["title"]]
        if task["flags"]:
            for f in task["flags"].split(","):
                f = f.strip()
                if f:
                    parts.append(f"[{f}]")
        if task["priority"] and task["priority"] != "minor":
            parts.append(f"!{task['priority']}")
        if task["effort_hours"]:
            parts.append(f"~{task['effort_hours']}h")
        if task["start_date"]:
            parts.append(f">{task['start_date']}")
        if task["due_date"]:
            parts.append(f"<{task['due_date']}")
        content = " ".join(parts)
        line = f"{indent}- [{done}] {content}  # {task['created_at']}"
        if task["completed_at"]:
            line += f"  ## {task['completed_at']}"
        lines.append(line)
        lines.extend(_serialize_tasks_dfs(tasks, parent_id=task["id"]))
    return lines


def _serialize(projects: list, tasks: list) -> str:
    lines = []
    for project in sorted(projects, key=lambda p: p["position"]):
        lines.append(f"# {project['name']}  # {project['created_at']}")
        lines.append("")
        proj_tasks = [t for t in tasks if t["project_id"] == project["id"]]
        lines.extend(_serialize_tasks_dfs(proj_tasks))
        lines.append("")
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _save_active() -> None:
    global _file_mtime
    content = _serialize(_projects, _tasks)
    _atomic_write(TASKS_FILE, content)
    _file_mtime = TASKS_FILE.stat().st_mtime if TASKS_FILE.exists() else -1.0


def _save_archive() -> None:
    global _archive_mtime
    content = _serialize(_archived_projects, _archived_tasks)
    _atomic_write(ARCHIVE_FILE, content)
    _archive_mtime = ARCHIVE_FILE.stat().st_mtime if ARCHIVE_FILE.exists() else -1.0


# ── init / reload ─────────────────────────────────────────────────────────────

def init_storage() -> None:
    global TASKS_FILE, ARCHIVE_FILE
    TASKS_FILE = get_storage_path()
    ARCHIVE_FILE = TASKS_FILE.parent / (TASKS_FILE.stem + ".archive.txt")
    _reload_all()


def _reload_all() -> None:
    global _projects, _tasks, _archived_projects, _archived_tasks
    global _id_counter, _id_map, _file_mtime, _archive_mtime

    _id_counter = 0
    _id_map = {}

    _projects, _tasks = _resolve_file(TASKS_FILE)
    _archived_projects, _archived_tasks = _resolve_file(ARCHIVE_FILE)

    _file_mtime = TASKS_FILE.stat().st_mtime if TASKS_FILE.exists() else -1.0
    _archive_mtime = ARCHIVE_FILE.stat().st_mtime if ARCHIVE_FILE.exists() else -1.0


def reload_if_changed() -> None:
    current_mtime = TASKS_FILE.stat().st_mtime if TASKS_FILE.exists() else -1.0
    current_archive_mtime = ARCHIVE_FILE.stat().st_mtime if ARCHIVE_FILE.exists() else -1.0
    if current_mtime != _file_mtime or current_archive_mtime != _archive_mtime:
        _reload_all()


# ── projects ──────────────────────────────────────────────────────────────────

def create_project(name: str) -> int:
    project = {
        "id": _next_id(),
        "name": name,
        "created_at": datetime.now().isoformat(),
        "archived": 0,
        "position": len(_projects),
    }
    _id_map[project["id"]] = project
    _projects.append(project)
    _save_active()
    return project["id"]


def get_project(project_id: int) :
    return _id_map.get(project_id)


def get_all_projects() -> list:
    return list(_projects)


def get_archived_projects() -> list:
    return list(_archived_projects)


def archive_project(project_id: int) -> None:
    project = _id_map.get(project_id)
    if not project or project not in _projects:
        return
    _projects.remove(project)
    project["archived"] = 1
    _archived_projects.append(project)
    proj_tasks = [t for t in _tasks if t["project_id"] == project_id]
    for t in proj_tasks:
        t["archived"] = 1
        _tasks.remove(t)
        _archived_tasks.append(t)
    _save_active()
    _save_archive()


def restore_project(project_id: int) -> None:
    project = _id_map.get(project_id)
    if not project or project not in _archived_projects:
        return
    _archived_projects.remove(project)
    project["archived"] = 0
    project["position"] = len(_projects)
    _projects.append(project)
    proj_tasks = [t for t in _archived_tasks if t["project_id"] == project_id]
    for t in proj_tasks:
        t["archived"] = 0
        _archived_tasks.remove(t)
        _tasks.append(t)
    _save_active()
    _save_archive()


def move_project(project_id: int, insert_before_id) -> bool:
    project = _id_map.get(project_id)
    if not project or project not in _projects:
        return False
    _projects.remove(project)
    if insert_before_id is not None:
        ids = [p["id"] for p in _projects]
        if insert_before_id in ids:
            _projects.insert(ids.index(insert_before_id), project)
        else:
            _projects.append(project)
    else:
        _projects.append(project)
    for pos, p in enumerate(_projects):
        p["position"] = pos
    _save_active()
    return True


# ── tasks ─────────────────────────────────────────────────────────────────────

def _get_subtask_ids_in(task_id: int, task_list: list) -> list[int]:
    result = []
    for t in task_list:
        if t["parent_id"] == task_id:
            result.append(t["id"])
            result.extend(_get_subtask_ids_in(t["id"], task_list))
    return result


def create_task(project_id: int, title: str, priority: str, effort_hours: int,
                parent_id=None, start_date=None, due_date=None) -> int:
    level = 0
    if parent_id is not None:
        parent = _id_map.get(parent_id)
        if parent:
            level = parent["level"] + 1
            if level > 3:
                raise ValueError("Maximum subtask depth (3) exceeded")

    siblings = [t for t in _tasks
                if t["project_id"] == project_id
                and t["parent_id"] == parent_id
                and t["archived"] == 0]
    position = len(siblings)

    task = {
        "id": _next_id(),
        "project_id": project_id,
        "parent_id": parent_id,
        "title": title,
        "priority": priority,
        "effort_hours": effort_hours,
        "level": level,
        "created_at": datetime.now().isoformat(),
        "completed_at": None,
        "archived": 0,
        "position": position,
        "start_date": start_date,
        "due_date": due_date,
        "flags": "",
        "_cascade_ts": None,
    }
    _id_map[task["id"]] = task
    _tasks.append(task)
    _save_active()
    return task["id"]


def get_task(task_id: int) :
    return _id_map.get(task_id)


def get_tasks_by_project(project_id: int, include_archived: bool = False) -> list:
    if include_archived:
        return [t for t in _tasks + _archived_tasks if t["project_id"] == project_id]
    return [t for t in _tasks if t["project_id"] == project_id and t["archived"] == 0]


def get_archived_tasks_by_project(project_id: int) -> list:
    # Tasks archived individually (still in _tasks with archived=1) + archived project tasks
    return (
        [t for t in _tasks if t["project_id"] == project_id and t["archived"] == 1]
        + [t for t in _archived_tasks if t["project_id"] == project_id]
    )


def update_task(task_id: int, title=None, priority=None, effort_hours=None,
                start_date=_MISSING, due_date=_MISSING) -> None:
    task = _id_map.get(task_id)
    if not task:
        return
    if title is not None:
        task["title"] = title
    if priority is not None:
        task["priority"] = priority
    if effort_hours is not None:
        task["effort_hours"] = effort_hours
    if start_date is not _MISSING:
        task["start_date"] = start_date
    if due_date is not _MISSING:
        task["due_date"] = due_date
    _save_active()


def toggle_task_complete(task_id: int) -> list[int]:
    task = _id_map.get(task_id)
    if not task:
        return []

    subtask_ids = _get_subtask_ids_in(task_id, _tasks)
    affected_ids = []

    if task["completed_at"]:
        # Undo: revert task + subtasks completed at the same cascade timestamp
        cascade_ts = task.get("_cascade_ts") or task["completed_at"]
        task["completed_at"] = None
        task["_cascade_ts"] = None
        affected_ids = [task_id]
        for sid in subtask_ids:
            sub = _id_map.get(sid)
            if sub and (sub.get("_cascade_ts") == cascade_ts
                        or sub["completed_at"] == cascade_ts):
                sub["completed_at"] = None
                sub["_cascade_ts"] = None
                affected_ids.append(sid)
    else:
        now = datetime.now().isoformat()
        task["completed_at"] = now
        task["_cascade_ts"] = now
        affected_ids = [task_id]
        for sid in subtask_ids:
            sub = _id_map.get(sid)
            if sub and not sub["completed_at"]:
                sub["completed_at"] = now
                sub["_cascade_ts"] = now
                affected_ids.append(sid)

    _save_active()
    return affected_ids


def archive_task(task_id: int) -> list[int]:
    task = _id_map.get(task_id)
    if not task:
        return []
    subtask_ids = _get_subtask_ids_in(task_id, _tasks)
    all_ids = [task_id] + subtask_ids
    for tid in all_ids:
        t = _id_map.get(tid)
        if t and t in _tasks:
            t["archived"] = 1
            _tasks.remove(t)
            _archived_tasks.append(t)
    _save_active()
    _save_archive()
    return all_ids


def restore_task(task_id: int) -> list[int]:
    task = _id_map.get(task_id)
    if not task:
        return []
    subtask_ids = _get_subtask_ids_in(task_id, _archived_tasks)
    all_ids = [task_id] + subtask_ids
    for tid in all_ids:
        t = _id_map.get(tid)
        if t and t in _archived_tasks:
            t["archived"] = 0
            _archived_tasks.remove(t)
            _tasks.append(t)
    _save_active()
    _save_archive()
    return all_ids


def move_task(task_id: int, new_parent_id, insert_before_id) -> bool:
    task = _id_map.get(task_id)
    if not task:
        return False

    project_id = task["project_id"]
    new_level = 0
    if new_parent_id is not None:
        parent = _id_map.get(new_parent_id)
        if parent:
            new_level = parent["level"] + 1
            if new_level > 3:
                return False

    subtask_ids = _get_subtask_ids_in(task_id, _tasks)
    level_diff = new_level - task["level"]

    task["parent_id"] = new_parent_id
    task["level"] = new_level

    for sid in subtask_ids:
        sub = _id_map.get(sid)
        if sub:
            sub["level"] += level_diff

    # Reorder among new siblings
    if new_parent_id is None:
        siblings = [t for t in _tasks
                    if t["project_id"] == project_id
                    and t["parent_id"] is None
                    and t["id"] != task_id
                    and t["archived"] == 0]
    else:
        siblings = [t for t in _tasks
                    if t["parent_id"] == new_parent_id
                    and t["id"] != task_id
                    and t["archived"] == 0]

    siblings.sort(key=lambda t: t["position"])
    insert_idx = len(siblings)
    if insert_before_id is not None:
        for i, s in enumerate(siblings):
            if s["id"] == insert_before_id:
                insert_idx = i
                break

    siblings.insert(insert_idx, task)
    for pos, t in enumerate(siblings):
        t["position"] = pos

    _save_active()
    return True


# ── flags ─────────────────────────────────────────────────────────────────────

def get_all_flags() -> list[dict]:
    seen: dict = {}
    for task in _tasks + _archived_tasks:
        if task["flags"]:
            for name in task["flags"].split(","):
                name = name.strip()
                if name and name not in seen:
                    seen[name] = len(seen) + 1
    return [{"id": fid, "name": name} for name, fid in seen.items()]


def delete_flag(flag_id: int) -> None:
    flags = get_all_flags()
    target = next((f for f in flags if f["id"] == flag_id), None)
    if not target:
        return
    name = target["name"]
    for task in _tasks + _archived_tasks:
        if task["flags"]:
            parts = [f.strip() for f in task["flags"].split(",") if f.strip() != name]
            task["flags"] = ",".join(parts)
    _save_active()
    _save_archive()


def add_flag_to_task(task_id: int, flag_name: str) -> None:
    task = _id_map.get(task_id)
    if not task:
        return
    existing = [f.strip() for f in task["flags"].split(",") if f.strip()] if task["flags"] else []
    if flag_name not in existing:
        existing.append(flag_name)
        task["flags"] = ",".join(existing)
    _save_active()


def sync_task_flags(task_id: int, current_flags_str: str, new_flag_names: list) -> None:
    task = _id_map.get(task_id)
    if not task:
        return
    task["flags"] = ",".join(new_flag_names)
    _save_active()
