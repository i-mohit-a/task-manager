"""One-off migration: tasks.db → tasks.txt + tasks.archive.txt

Run once, then delete this script and tasks.db.

Usage:
    TASKMANAGER_DEV=1 python3 migrate_db_to_txt.py
"""

import os
import sqlite3
from pathlib import Path
from datetime import datetime

os.environ.setdefault("TASKMANAGER_DEV", "1")

import database as old_db
import storage as new_db


def row_to_dict(row):
    return dict(row) if row else None


def migrate():
    db_path = old_db.get_db_path()
    if not db_path.exists():
        print(f"No database found at {db_path}. Nothing to migrate.")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    new_db.init_storage()

    # -- Projects (active) --
    cursor = conn.execute(
        "SELECT * FROM projects WHERE archived = 0 ORDER BY position, created_at DESC"
    )
    active_projects = [dict(r) for r in cursor.fetchall()]

    # -- Projects (archived) --
    cursor = conn.execute(
        "SELECT * FROM projects WHERE archived = 1 ORDER BY created_at DESC"
    )
    archived_projects = [dict(r) for r in cursor.fetchall()]

    # Maps old DB id → new storage id
    proj_id_map: dict = {}
    task_id_map: dict = {}

    def migrate_project(old_proj, archived=False):
        pid = new_db.create_project(old_proj["name"])
        # Override created_at in the dict directly (create_project sets it to now)
        proj = new_db.get_project(pid)
        if proj:
            proj["created_at"] = old_proj["created_at"]
        proj_id_map[old_proj["id"]] = pid
        new_db._save_active()
        return pid

    def migrate_tasks_for_project(old_proj_id, new_proj_id):
        cursor = conn.execute(
            """SELECT t.*, GROUP_CONCAT(f.name) as flags
            FROM tasks t
            LEFT JOIN task_flags tf ON t.id = tf.task_id
            LEFT JOIN flags f ON tf.flag_id = f.id
            WHERE t.project_id = ? AND t.archived = 0
            GROUP BY t.id
            ORDER BY t.position, t.created_at""",
            (old_proj_id,)
        )
        tasks = [dict(r) for r in cursor.fetchall()]

        # Build by level, inserting parents first
        # Tasks are ordered by position so we process level 0, then their children naturally
        for task in tasks:
            old_parent_id = task["parent_id"]
            new_parent_id = task_id_map.get(old_parent_id) if old_parent_id else None

            tid = new_db.create_task(
                new_proj_id,
                task["title"],
                task["priority"],
                task["effort_hours"] or 0,
                parent_id=new_parent_id,
                start_date=task.get("start_date"),
                due_date=task.get("due_date"),
            )
            task_id_map[task["id"]] = tid

            # Restore metadata
            t = new_db.get_task(tid)
            if t:
                t["created_at"] = task["created_at"]
                if task.get("completed_at"):
                    t["completed_at"] = task["completed_at"]
                if task.get("flags"):
                    t["flags"] = task["flags"]

        new_db._save_active()

    def migrate_archived_tasks_for_project(old_proj_id, new_proj_id):
        cursor = conn.execute(
            """SELECT t.*, GROUP_CONCAT(f.name) as flags
            FROM tasks t
            LEFT JOIN task_flags tf ON t.id = tf.task_id
            LEFT JOIN flags f ON tf.flag_id = f.id
            WHERE t.project_id = ? AND t.archived = 1
            GROUP BY t.id
            ORDER BY t.position, t.created_at""",
            (old_proj_id,)
        )
        tasks = [dict(r) for r in cursor.fetchall()]

        for task in tasks:
            old_parent_id = task["parent_id"]
            new_parent_id = task_id_map.get(old_parent_id) if old_parent_id else None

            tid = new_db.create_task(
                new_proj_id,
                task["title"],
                task["priority"],
                task["effort_hours"] or 0,
                parent_id=new_parent_id,
                start_date=task.get("start_date"),
                due_date=task.get("due_date"),
            )
            task_id_map[task["id"]] = tid

            t = new_db.get_task(tid)
            if t:
                t["created_at"] = task["created_at"]
                if task.get("completed_at"):
                    t["completed_at"] = task["completed_at"]
                if task.get("flags"):
                    t["flags"] = task["flags"]

        # Archive them individually
        for task in tasks:
            new_tid = task_id_map.get(task["id"])
            if new_tid:
                new_db.archive_task(new_tid)

    print(f"Migrating {len(active_projects)} active projects...")
    for proj in active_projects:
        pid = migrate_project(proj)
        migrate_tasks_for_project(proj["id"], pid)
        print(f"  [active] {proj['name']}")

    print(f"Migrating {len(archived_projects)} archived projects...")
    for proj in archived_projects:
        pid = migrate_project(proj, archived=True)
        migrate_tasks_for_project(proj["id"], pid)
        migrate_archived_tasks_for_project(proj["id"], pid)
        new_db.archive_project(pid)
        print(f"  [archived] {proj['name']}")

    conn.close()

    txt_path = new_db.TASKS_FILE
    archive_path = new_db.ARCHIVE_FILE
    print(f"\nDone! Written to:")
    print(f"  {txt_path}")
    print(f"  {archive_path}")
    print(f"\nVerify the output, then run:")
    print(f"  rm {db_path}")
    print(f"  rm migrate_db_to_txt.py")


if __name__ == "__main__":
    migrate()
