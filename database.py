import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

_MISSING = object()


def get_db_path():
    """Get database path in user's Application Support directory."""
    if os.environ.get("TASKMANAGER_DEV"):
        return Path(__file__).parent / "tasks.db"
    app_support = Path.home() / "Library" / "Application Support" / "TaskManager"
    app_support.mkdir(parents=True, exist_ok=True)
    return app_support / "tasks.db"


DB_PATH = get_db_path()


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            parent_id INTEGER,
            title TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'minor',
            effort_hours INTEGER DEFAULT 0,
            level INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            archived INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (parent_id) REFERENCES tasks(id) ON DELETE CASCADE,
            CHECK (priority IN ('critical', 'major', 'minor')),
            CHECK (level >= 0 AND level <= 3)
        );

        CREATE TABLE IF NOT EXISTS flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS task_flags (
            task_id INTEGER NOT NULL,
            flag_id INTEGER NOT NULL,
            PRIMARY KEY (task_id, flag_id),
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (flag_id) REFERENCES flags(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_id);
    """)

    # Migrations: add columns if not exists (preserves existing data)
    cursor.execute("PRAGMA table_info(tasks)")
    columns = [row[1] for row in cursor.fetchall()]
    if "archived" not in columns:
        cursor.execute("ALTER TABLE tasks ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
    if "start_date" not in columns:
        cursor.execute("ALTER TABLE tasks ADD COLUMN start_date TEXT")
    if "due_date" not in columns:
        cursor.execute("ALTER TABLE tasks ADD COLUMN due_date TEXT")
    if "position" not in columns:
        cursor.execute("ALTER TABLE tasks ADD COLUMN position INTEGER DEFAULT 0")
        # Initialize positions from created_at order within each sibling group
        cursor.execute("""
            UPDATE tasks SET position = (
                SELECT COUNT(*) FROM tasks t2
                WHERE t2.project_id = tasks.project_id
                AND (t2.parent_id = tasks.parent_id OR (t2.parent_id IS NULL AND tasks.parent_id IS NULL))
                AND t2.created_at < tasks.created_at
            )
        """)

    # Create index for archived column (after migration ensures column exists)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_archived ON tasks(archived)")

    conn.commit()
    conn.close()


def create_project(name):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO projects (name, created_at) VALUES (?, ?)",
        (name, datetime.now().isoformat())
    )
    project_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return project_id


def get_all_projects():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM projects ORDER BY created_at DESC")
    projects = cursor.fetchall()
    conn.close()
    return projects


def delete_project(project_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    conn.close()


def create_task(project_id, title, priority, effort_hours, parent_id=None, start_date=None, due_date=None):
    conn = get_connection()
    cursor = conn.cursor()
    level = 0
    if parent_id:
        cursor.execute("SELECT level FROM tasks WHERE id = ?", (parent_id,))
        parent = cursor.fetchone()
        if parent:
            level = parent["level"] + 1
            if level > 3:
                conn.close()
                raise ValueError("Maximum subtask depth (3) exceeded")
    cursor.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM tasks WHERE project_id = ? AND parent_id IS ? AND archived = 0",
        (project_id, parent_id)
    )
    position = cursor.fetchone()[0]
    cursor.execute(
        """INSERT INTO tasks (project_id, parent_id, title, priority, effort_hours, level, created_at, start_date, due_date, position)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (project_id, parent_id, title, priority, effort_hours, level, datetime.now().isoformat(), start_date, due_date, position)
    )
    task_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return task_id


def get_tasks_by_project(project_id, include_archived=False):
    conn = get_connection()
    cursor = conn.cursor()
    if include_archived:
        cursor.execute(
            """SELECT t.*, GROUP_CONCAT(f.name) as flags
            FROM tasks t
            LEFT JOIN task_flags tf ON t.id = tf.task_id
            LEFT JOIN flags f ON tf.flag_id = f.id
            WHERE t.project_id = ?
            GROUP BY t.id
            ORDER BY t.position, t.created_at""",
            (project_id,)
        )
    else:
        cursor.execute(
            """SELECT t.*, GROUP_CONCAT(f.name) as flags
            FROM tasks t
            LEFT JOIN task_flags tf ON t.id = tf.task_id
            LEFT JOIN flags f ON tf.flag_id = f.id
            WHERE t.project_id = ? AND t.archived = 0
            GROUP BY t.id
            ORDER BY t.position, t.created_at""",
            (project_id,)
        )
    tasks = cursor.fetchall()
    conn.close()
    return tasks


def get_task(task_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT t.*, GROUP_CONCAT(f.name) as flags
        FROM tasks t
        LEFT JOIN task_flags tf ON t.id = tf.task_id
        LEFT JOIN flags f ON tf.flag_id = f.id
        WHERE t.id = ?
        GROUP BY t.id""",
        (task_id,)
    )
    task = cursor.fetchone()
    conn.close()
    return task


def update_task(task_id, title=None, priority=None, effort_hours=None, start_date=_MISSING, due_date=_MISSING):
    conn = get_connection()
    cursor = conn.cursor()
    updates = []
    params = []
    if title is not None:
        updates.append("title = ?")
        params.append(title)
    if priority is not None:
        updates.append("priority = ?")
        params.append(priority)
    if effort_hours is not None:
        updates.append("effort_hours = ?")
        params.append(effort_hours)
    if start_date is not _MISSING:
        updates.append("start_date = ?")
        params.append(start_date)
    if due_date is not _MISSING:
        updates.append("due_date = ?")
        params.append(due_date)
    if updates:
        params.append(task_id)
        cursor.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
    conn.close()


def get_all_subtask_ids(cursor, task_id):
    """Recursively get all subtask IDs for a task."""
    cursor.execute("SELECT id FROM tasks WHERE parent_id = ?", (task_id,))
    subtasks = cursor.fetchall()
    ids = []
    for subtask in subtasks:
        ids.append(subtask["id"])
        ids.extend(get_all_subtask_ids(cursor, subtask["id"]))
    return ids


def toggle_task_complete(task_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT completed_at FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()
    affected_ids = []
    if task:
        subtask_ids = get_all_subtask_ids(cursor, task_id)

        if task["completed_at"]:
            # Undo: only revert subtasks completed at the same timestamp as the parent
            parent_completed_at = task["completed_at"]
            cursor.execute("UPDATE tasks SET completed_at = NULL WHERE id = ?", (task_id,))
            affected_ids = [task_id]
            if subtask_ids:
                placeholders = ",".join("?" * len(subtask_ids))
                cursor.execute(
                    f"SELECT id FROM tasks WHERE id IN ({placeholders}) AND completed_at = ?",
                    subtask_ids + [parent_completed_at]
                )
                matched = [row["id"] for row in cursor.fetchall()]
                if matched:
                    match_placeholders = ",".join("?" * len(matched))
                    cursor.execute(
                        f"UPDATE tasks SET completed_at = NULL WHERE id IN ({match_placeholders})",
                        matched
                    )
                    affected_ids.extend(matched)
        else:
            # Complete: mark parent and only subtasks not already done
            now = datetime.now().isoformat()
            cursor.execute("UPDATE tasks SET completed_at = ? WHERE id = ?", (now, task_id))
            affected_ids = [task_id]
            if subtask_ids:
                placeholders = ",".join("?" * len(subtask_ids))
                cursor.execute(
                    f"SELECT id FROM tasks WHERE id IN ({placeholders}) AND completed_at IS NULL",
                    subtask_ids
                )
                to_complete = [row["id"] for row in cursor.fetchall()]
                if to_complete:
                    complete_placeholders = ",".join("?" * len(to_complete))
                    cursor.execute(
                        f"UPDATE tasks SET completed_at = ? WHERE id IN ({complete_placeholders})",
                        [now] + to_complete
                    )
                    affected_ids.extend(to_complete)
    conn.commit()
    conn.close()
    return affected_ids


def archive_task(task_id):
    """Archive a task and all its subtasks."""
    conn = get_connection()
    cursor = conn.cursor()
    subtask_ids = get_all_subtask_ids(cursor, task_id)
    all_ids = [task_id] + subtask_ids
    placeholders = ",".join("?" * len(all_ids))
    cursor.execute(
        f"UPDATE tasks SET archived = 1 WHERE id IN ({placeholders})",
        all_ids
    )
    conn.commit()
    conn.close()
    return all_ids


def restore_task(task_id):
    """Restore a task and all its subtasks from archive."""
    conn = get_connection()
    cursor = conn.cursor()
    subtask_ids = get_all_subtask_ids(cursor, task_id)
    all_ids = [task_id] + subtask_ids
    placeholders = ",".join("?" * len(all_ids))
    cursor.execute(
        f"UPDATE tasks SET archived = 0 WHERE id IN ({placeholders})",
        all_ids
    )
    conn.commit()
    conn.close()
    return all_ids


def move_task(task_id, new_parent_id, insert_before_id):
    """
    Move a task to a new parent, inserting it before insert_before_id among siblings.
    new_parent_id: None for root level, or parent task id
    insert_before_id: sibling task id to insert before, or None to append at end
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Get task info
    cursor.execute("SELECT project_id, parent_id, level FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()
    if not task:
        conn.close()
        return False

    project_id = task["project_id"]

    # Calculate new level
    new_level = 0
    if new_parent_id:
        cursor.execute("SELECT level FROM tasks WHERE id = ?", (new_parent_id,))
        parent = cursor.fetchone()
        if parent:
            new_level = parent["level"] + 1
            if new_level > 3:
                conn.close()
                return False

    # Get all subtasks to update their levels
    subtask_ids = get_all_subtask_ids(cursor, task_id)
    level_diff = new_level - task["level"]

    # Update the task's parent and level
    cursor.execute(
        "UPDATE tasks SET parent_id = ?, level = ? WHERE id = ?",
        (new_parent_id, new_level, task_id)
    )

    # Update subtask levels
    if subtask_ids and level_diff != 0:
        for sub_id in subtask_ids:
            cursor.execute(
                "UPDATE tasks SET level = level + ? WHERE id = ?",
                (level_diff, sub_id)
            )

    # Renumber positions among new siblings (excluding the moved task, then insert it)
    if new_parent_id is None:
        cursor.execute(
            "SELECT id FROM tasks WHERE project_id = ? AND parent_id IS NULL AND id != ? AND archived = 0 ORDER BY position, created_at",
            (project_id, task_id)
        )
    else:
        cursor.execute(
            "SELECT id FROM tasks WHERE parent_id = ? AND id != ? AND archived = 0 ORDER BY position, created_at",
            (new_parent_id, task_id)
        )
    siblings = [row["id"] for row in cursor.fetchall()]

    # Insert task_id at the right spot
    insert_idx = len(siblings)
    if insert_before_id is not None:
        for i, sid in enumerate(siblings):
            if sid == insert_before_id:
                insert_idx = i
                break

    siblings.insert(insert_idx, task_id)

    for pos, tid in enumerate(siblings):
        cursor.execute("UPDATE tasks SET position = ? WHERE id = ?", (pos, tid))

    conn.commit()
    conn.close()
    return True


def get_task_with_subtree_ids(task_id):
    """Get a task ID and all its subtask IDs for a task."""
    conn = get_connection()
    cursor = conn.cursor()
    subtask_ids = get_all_subtask_ids(cursor, task_id)
    conn.close()
    return [task_id] + subtask_ids


def get_archived_tasks_by_project(project_id):
    """Get archived tasks for a project."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT t.*, GROUP_CONCAT(f.name) as flags
        FROM tasks t
        LEFT JOIN task_flags tf ON t.id = tf.task_id
        LEFT JOIN flags f ON tf.flag_id = f.id
        WHERE t.project_id = ? AND t.archived = 1
        GROUP BY t.id
        ORDER BY t.position, t.created_at""",
        (project_id,)
    )
    tasks = cursor.fetchall()
    conn.close()
    return tasks


def delete_task(task_id):
    """Permanently delete a task (use archive_task instead for soft delete)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()


def get_or_create_flag(name):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM flags WHERE name = ?", (name,))
    flag = cursor.fetchone()
    if flag:
        flag_id = flag["id"]
    else:
        cursor.execute("INSERT INTO flags (name) VALUES (?)", (name,))
        flag_id = cursor.lastrowid
        conn.commit()
    conn.close()
    return flag_id


def add_flag_to_task(task_id, flag_name):
    flag_id = get_or_create_flag(flag_name)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO task_flags (task_id, flag_id) VALUES (?, ?)",
        (task_id, flag_id)
    )
    conn.commit()
    conn.close()


def remove_flag_from_task(task_id, flag_name):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """DELETE FROM task_flags WHERE task_id = ? AND flag_id = (
            SELECT id FROM flags WHERE name = ?
        )""",
        (task_id, flag_name)
    )
    conn.commit()
    conn.close()


def get_all_flags():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM flags ORDER BY name")
    flags = [row["name"] for row in cursor.fetchall()]
    conn.close()
    return flags


def build_task_tree(tasks):
    task_dict = {}
    for task in tasks:
        task_data = dict(task)
        task_data["children"] = []
        task_dict[task_data["id"]] = task_data

    roots = []
    for task_data in task_dict.values():
        if task_data["parent_id"] is None:
            roots.append(task_data)
        else:
            parent = task_dict.get(task_data["parent_id"])
            if parent:
                parent["children"].append(task_data)

    def sort_by_completion(items):
        for item in items:
            if item["children"]:
                item["children"] = sort_by_completion(item["children"])
        return sorted(items, key=lambda x: (0 if x["completed_at"] is None else 1))

    return sort_by_completion(roots)


def parse_task_input(text):
    """
    Parse task input with inline syntax:
    - Flags: [flag] extracted and removed from title
    - Priority: critical or major or minor (default: minor)
    - Effort: -4h or -2h (number followed by h)

    Example: "Build login page [frontend] [auth] major -8h"
    Returns: {"title": "Build login page", "priority": "major", "effort_hours": 8, "flags": ["frontend", "auth"]}
    """
    result = {
        "title": "",
        "priority": "minor",
        "effort_hours": 0,
        "flags": [],
        "start_date": None,
        "due_date": None
    }

    # Extract flags [something]
    flags = re.findall(r'\[([^\[\]]+)\]', text)
    result["flags"] = [f.strip() for f in flags if f.strip()]
    text = re.sub(r'\[[^\[\]]+\]', '', text)

    # Extract priority: !critical, !major, !minor (! prefix required)
    priority_match = re.search(r'!(critical|major|minor)\b', text, re.IGNORECASE)
    if priority_match:
        result["priority"] = priority_match.group(1).lower()
        text = re.sub(r'!(critical|major|minor)\b', '', text, flags=re.IGNORECASE)

    # Extract effort ~4h
    effort_match = re.search(r'~(\d+\.?\d*)h\b', text, re.IGNORECASE)
    if effort_match:
        result["effort_hours"] = int(float(effort_match.group(1)))
        text = re.sub(r'~(\d+\.?\d*)h\b', '', text, flags=re.IGNORECASE)

    # Extract start date >YYYY-MM-DD
    start_match = re.search(r'>(\d{4}-\d{2}-\d{2})', text)
    if start_match:
        result["start_date"] = start_match.group(1)
        text = re.sub(r'>(\d{4}-\d{2}-\d{2})', '', text)

    # Extract due date <YYYY-MM-DD
    due_match = re.search(r'<(\d{4}-\d{2}-\d{2})', text)
    if due_match:
        result["due_date"] = due_match.group(1)
        text = re.sub(r'<(\d{4}-\d{2}-\d{2})', '', text)

    # Clean up title
    result["title"] = ' '.join(text.split()).strip()

    return result
