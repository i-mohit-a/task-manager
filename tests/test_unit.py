"""Unit tests for pure/stateless functions.

Only covers logic NOT already exercised end-to-end by test_integration.py:
- parse_task_input()  — token extraction and title normalisation
- flag_color()        — hash-based colour index
- build_task_tree()   — flat-list → nested tree with sort order
"""

import pytest
from task_parser import parse_task_input
from app import flag_color, build_task_tree
import database as db


# ── parse_task_input ──────────────────────────────────────────────────────────

class TestParseTaskInput:
    """Tests parse_task_input() in isolation with edge-case inputs."""

    def test_title_only_defaults(self):
        r = parse_task_input("Simple task")
        assert r["title"] == "Simple task"
        assert r["priority"] == "minor"
        assert r["effort_hours"] == 0
        assert r["flags"] == []
        assert r["start_date"] is None
        assert r["due_date"] is None

    def test_all_fields_combined(self):
        r = parse_task_input(
            "Build API [backend] [auth] !critical ~8h >2026-01-01 <2026-01-31"
        )
        assert r["title"] == "Build API"
        assert r["priority"] == "critical"
        assert r["effort_hours"] == 8
        assert sorted(r["flags"]) == ["auth", "backend"]
        assert r["start_date"] == "2026-01-01"
        assert r["due_date"] == "2026-01-31"

    def test_priority_case_insensitive(self):
        assert parse_task_input("T !CRITICAL")["priority"] == "critical"
        assert parse_task_input("T !Major")["priority"] == "major"
        assert parse_task_input("T !MINOR")["priority"] == "minor"

    def test_no_priority_token_defaults_to_minor(self):
        assert parse_task_input("Task without priority")["priority"] == "minor"

    def test_effort_decimal_is_truncated_to_int(self):
        # int(float("1.9")) == 1
        assert parse_task_input("Task ~1.9h")["effort_hours"] == 1

    def test_effort_whole_number(self):
        assert parse_task_input("Task ~10h")["effort_hours"] == 10

    def test_no_effort_token_defaults_to_zero(self):
        assert parse_task_input("Task")["effort_hours"] == 0

    def test_multiple_flags_all_extracted(self):
        r = parse_task_input("Task [a] [b] [c]")
        assert r["flags"] == ["a", "b", "c"]

    def test_flags_stripped_from_title(self):
        r = parse_task_input("[flag] Task title [other]")
        assert r["title"] == "Task title"
        assert "flag" in r["flags"]
        assert "other" in r["flags"]

    def test_no_flags_returns_empty_list(self):
        assert parse_task_input("Task")["flags"] == []

    def test_tokens_stripped_from_title(self):
        r = parse_task_input("Fix !critical bug ~2h")
        assert r["title"] == "Fix bug"

    def test_whitespace_normalised_in_title(self):
        r = parse_task_input("  lots   of   spaces  ")
        assert r["title"] == "lots of spaces"

    def test_empty_string_gives_empty_title(self):
        r = parse_task_input("")
        assert r["title"] == ""
        assert r["flags"] == []

    def test_only_flag_gives_empty_title(self):
        r = parse_task_input("[only-flag]")
        assert r["title"] == ""
        assert r["flags"] == ["only-flag"]

    def test_start_date_extracted_and_not_in_title(self):
        r = parse_task_input("Task >2026-06-15")
        assert r["start_date"] == "2026-06-15"
        assert "2026-06-15" not in r["title"]

    def test_due_date_extracted_and_not_in_title(self):
        r = parse_task_input("Task <2026-12-31")
        assert r["due_date"] == "2026-12-31"
        assert "2026-12-31" not in r["title"]

    def test_no_dates_return_none(self):
        r = parse_task_input("Task")
        assert r["start_date"] is None
        assert r["due_date"] is None


# ── flag_color ────────────────────────────────────────────────────────────────

class TestFlagColor:
    def test_returns_integer_in_0_to_7_range(self):
        for name in ["auth", "frontend", "backend", "bug", "release", "x"]:
            c = flag_color(name)
            assert isinstance(c, int), f"flag_color({name!r}) should be int"
            assert 0 <= c <= 7, f"flag_color({name!r}) = {c} out of range"

    def test_same_name_always_returns_same_color(self):
        assert flag_color("auth") == flag_color("auth")
        assert flag_color("backend") == flag_color("backend")

    def test_empty_string_returns_zero(self):
        # sum of empty sequence is 0; 0 % 8 == 0
        assert flag_color("") == 0

    def test_single_character(self):
        assert flag_color("a") == ord("a") % 8


# ── build_task_tree ───────────────────────────────────────────────────────────

class TestBuildTaskTree:
    """
    build_task_tree() converts a flat list of task dicts into a nested tree
    and sorts incomplete tasks before completed ones at every level.
    """

    def _task(self, id, parent_id=None, completed_at=None):
        """Minimal task dict compatible with build_task_tree()."""
        return {"id": id, "parent_id": parent_id, "completed_at": completed_at}

    def test_empty_input_returns_empty_list(self):
        assert build_task_tree([]) == []

    def test_flat_tasks_all_become_roots(self):
        tasks = [self._task(1), self._task(2), self._task(3)]
        tree = build_task_tree(tasks)
        assert len(tree) == 3
        assert all(t["children"] == [] for t in tree)

    def test_child_is_nested_under_parent(self):
        tasks = [self._task(1), self._task(2, parent_id=1)]
        tree = build_task_tree(tasks)
        assert len(tree) == 1
        root = tree[0]
        assert root["id"] == 1
        assert len(root["children"]) == 1
        assert root["children"][0]["id"] == 2

    def test_multiple_children_nested_correctly(self):
        tasks = [
            self._task(1),
            self._task(2, parent_id=1),
            self._task(3, parent_id=1),
        ]
        tree = build_task_tree(tasks)
        root = tree[0]
        child_ids = {c["id"] for c in root["children"]}
        assert child_ids == {2, 3}

    def test_incomplete_sorted_before_complete_at_root(self):
        tasks = [
            self._task(1, completed_at="2026-01-01"),  # done
            self._task(2, completed_at=None),           # incomplete
            self._task(3, completed_at="2026-01-02"),  # done
        ]
        tree = build_task_tree(tasks)
        assert tree[0]["id"] == 2          # incomplete first
        assert tree[0]["completed_at"] is None

    def test_incomplete_children_sorted_before_complete_children(self):
        tasks = [
            self._task(1),
            self._task(2, parent_id=1, completed_at="2026-01-01"),  # done child
            self._task(3, parent_id=1, completed_at=None),           # incomplete child
        ]
        tree = build_task_tree(tasks)
        children = tree[0]["children"]
        assert children[0]["id"] == 3   # incomplete first
        assert children[1]["id"] == 2   # completed last

    def test_orphaned_child_excluded_from_tree(self):
        # Task with parent_id=99 but no task with id=99 in list
        tasks = [self._task(1), self._task(2, parent_id=99)]
        tree = build_task_tree(tasks)
        # Only root 1 appears; orphaned task 2 is silently dropped
        assert len(tree) == 1
        assert tree[0]["id"] == 1

    def test_children_field_added_to_all_nodes(self):
        tasks = [self._task(1), self._task(2, parent_id=1)]
        tree = build_task_tree(tasks)
        assert "children" in tree[0]
        assert "children" in tree[0]["children"][0]


# ── update_task sentinel ───────────────────────────────────────────────────────

class TestUpdateTask:
    """Tests update_task() _MISSING sentinel: passing None explicitly clears a date."""

    def test_clears_start_date_when_none_passed(self, monkeypatch, tmp_path):
        db_file = tmp_path / "test.db"
        monkeypatch.setattr(db, "DB_PATH", db_file)
        db.init_db()

        pid = db.create_project("P")
        tid = db.create_task(pid, "Task", "minor", 0, start_date="2026-01-01")

        assert db.get_task(tid)["start_date"] == "2026-01-01"

        db.update_task(tid, start_date=None)
        assert db.get_task(tid)["start_date"] is None

    def test_clears_due_date_when_none_passed(self, monkeypatch, tmp_path):
        db_file = tmp_path / "test.db"
        monkeypatch.setattr(db, "DB_PATH", db_file)
        db.init_db()

        pid = db.create_project("P")
        tid = db.create_task(pid, "Task", "minor", 0, due_date="2026-12-31")

        assert db.get_task(tid)["due_date"] == "2026-12-31"

        db.update_task(tid, due_date=None)
        assert db.get_task(tid)["due_date"] is None

    def test_missing_sentinel_preserves_existing_date(self, monkeypatch, tmp_path):
        db_file = tmp_path / "test.db"
        monkeypatch.setattr(db, "DB_PATH", db_file)
        db.init_db()

        pid = db.create_project("P")
        tid = db.create_task(pid, "Task", "minor", 0, start_date="2026-06-15")

        # Updating title only — start_date uses _MISSING default, should not be touched
        db.update_task(tid, title="New title")
        assert db.get_task(tid)["start_date"] == "2026-06-15"
