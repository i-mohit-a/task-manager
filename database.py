import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from task_parser import parse_task_input  # noqa: F401 — re-exported for callers

logger = logging.getLogger(__name__)

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


@contextmanager
def _db_conn():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with _db_conn() as conn:
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
        cursor.execute("PRAGMA table_info(projects)")
        proj_columns = [row[1] for row in cursor.fetchall()]
        if "archived" not in proj_columns:
            cursor.execute("ALTER TABLE projects ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
        if "position" not in proj_columns:
            cursor.execute("ALTER TABLE projects ADD COLUMN position INTEGER DEFAULT 0")
            cursor.execute("""
                UPDATE projects SET position = (
                    SELECT COUNT(*) FROM projects p2 WHERE p2.created_at > projects.created_at
                )
            """)

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


def create_project(name):
    with _db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM projects WHERE archived = 0")
        position = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO projects (name, created_at, position) VALUES (?, ?, ?)",
            (name, datetime.now().isoformat(), position)
        )
        return cursor.lastrowid


def get_project(project_id):
    with _db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        return cursor.fetchone()


def get_all_projects():
    with _db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM projects WHERE archived = 0 ORDER BY position, created_at DESC")
        return cursor.fetchall()


def get_archived_projects():
    with _db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM projects WHERE archived = 1 ORDER BY created_at DESC")
        return cursor.fetchall()


def archive_project(project_id):
    with _db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE projects SET archived = 1 WHERE id = ?", (project_id,))
        cursor.execute("UPDATE tasks SET archived = 1 WHERE project_id = ?", (project_id,))


def restore_project(project_id):
    with _db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE projects SET archived = 0 WHERE id = ?", (project_id,))
        cursor.execute("UPDATE tasks SET archived = 0 WHERE project_id = ?", (project_id,))


def delete_project(project_id):
    with _db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM projects WHERE id = ?", (project_id,))


def move_project(project_id, insert_before_id):
    with _db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM projects WHERE archived = 0 ORDER BY position, created_at DESC")
        ids = [row[0] for row in cursor.fetchall()]
        if project_id not in ids:
            return False
        ids.remove(project_id)
        if insert_before_id and insert_before_id in ids:
            ids.insert(ids.index(insert_before_id), project_id)
        else:
            ids.append(project_id)
        for pos, pid in enumerate(ids):
            cursor.execute("UPDATE projects SET position = ? WHERE id = ?", (pos, pid))
        return True


def create_task(project_id, title, priority, effort_hours, parent_id=None, start_date=None, due_date=None):
    with _db_conn() as conn:
        cursor = conn.cursor()
        level = 0
        if parent_id:
            cursor.execute("SELECT level FROM tasks WHERE id = ?", (parent_id,))
            parent = cursor.fetchone()
            if parent:
                level = parent["level"] + 1
                if level > 3:
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
        return cursor.lastrowid


def get_tasks_by_project(project_id, include_archived=False):
    with _db_conn() as conn:
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
        return cursor.fetchall()


def get_task(task_id):
    with _db_conn() as conn:
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
        return cursor.fetchone()


def update_task(task_id, title=None, priority=None, effort_hours=None, start_date=_MISSING, due_date=_MISSING):
    with _db_conn() as conn:
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
    with _db_conn() as conn:
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
        return affected_ids


def archive_task(task_id):
    """Archive a task and all its subtasks."""
    with _db_conn() as conn:
        cursor = conn.cursor()
        subtask_ids = get_all_subtask_ids(cursor, task_id)
        all_ids = [task_id] + subtask_ids
        placeholders = ",".join("?" * len(all_ids))
        cursor.execute(
            f"UPDATE tasks SET archived = 1 WHERE id IN ({placeholders})",
            all_ids
        )
        return all_ids


def restore_task(task_id):
    """Restore a task and all its subtasks from archive."""
    with _db_conn() as conn:
        cursor = conn.cursor()
        subtask_ids = get_all_subtask_ids(cursor, task_id)
        all_ids = [task_id] + subtask_ids
        placeholders = ",".join("?" * len(all_ids))
        cursor.execute(
            f"UPDATE tasks SET archived = 0 WHERE id IN ({placeholders})",
            all_ids
        )
        return all_ids


def move_task(task_id, new_parent_id, insert_before_id):
    """
    Move a task to a new parent, inserting it before insert_before_id among siblings.
    new_parent_id: None for root level, or parent task id
    insert_before_id: sibling task id to insert before, or None to append at end
    """
    with _db_conn() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT project_id, parent_id, level FROM tasks WHERE id = ?", (task_id,))
        task = cursor.fetchone()
        if not task:
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

        insert_idx = len(siblings)
        if insert_before_id is not None:
            for i, sid in enumerate(siblings):
                if sid == insert_before_id:
                    insert_idx = i
                    break

        siblings.insert(insert_idx, task_id)

        for pos, tid in enumerate(siblings):
            cursor.execute("UPDATE tasks SET position = ? WHERE id = ?", (pos, tid))

        return True


def get_task_with_subtree_ids(task_id):
    """Get a task ID and all its subtask IDs for a task."""
    with _db_conn() as conn:
        cursor = conn.cursor()
        subtask_ids = get_all_subtask_ids(cursor, task_id)
        return [task_id] + subtask_ids


def get_archived_tasks_by_project(project_id):
    """Get archived tasks for a project."""
    with _db_conn() as conn:
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
        return cursor.fetchall()


def delete_task(task_id):
    """Permanently delete a task (use archive_task instead for soft delete)."""
    with _db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))


def get_or_create_flag(name):
    with _db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM flags WHERE name = ?", (name,))
        flag = cursor.fetchone()
        if flag:
            return flag["id"]
        cursor.execute("INSERT INTO flags (name) VALUES (?)", (name,))
        return cursor.lastrowid


def add_flag_to_task(task_id, flag_name):
    flag_id = get_or_create_flag(flag_name)
    with _db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO task_flags (task_id, flag_id) VALUES (?, ?)",
            (task_id, flag_id)
        )


def remove_flag_from_task(task_id, flag_name):
    with _db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """DELETE FROM task_flags WHERE task_id = ? AND flag_id = (
                SELECT id FROM flags WHERE name = ?
            )""",
            (task_id, flag_name)
        )


def sync_task_flags(task_id, current_flags_str, new_flag_names):
    current = set(current_flags_str.split(",") if current_flags_str else [])
    new = set(new_flag_names)
    for flag in current - new:
        remove_flag_from_task(task_id, flag)
    for flag in new - current:
        add_flag_to_task(task_id, flag)


def get_all_flags():
    with _db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM flags ORDER BY name")
        return [{"id": row["id"], "name": row["name"]} for row in cursor.fetchall()]


def delete_flag(flag_id):
    with _db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM flags WHERE id = ?", (flag_id,))
