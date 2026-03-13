"""Integration tests for task-manager routes.

Each test exercises the full stack: HTTP handler → database → response.
The `client` fixture (conftest.py) wires every test to an isolated temp DB.
"""

import database as db

AJAX = {"Accept": "application/json"}


# ── helpers ───────────────────────────────────────────────────────────────────

def _create_project(client, name="My Project"):
    r = client.post("/projects/new", data={"name": name}, headers=AJAX)
    return r.json()["project"]["id"]


def _add_task(client, project_id, title="Task"):
    r = client.post(f"/projects/{project_id}/tasks/quick",
                    data={"title": title}, headers=AJAX)
    return r.json()["task"]["id"]


def _add_subtask(client, parent_id, content="Subtask"):
    r = client.post(f"/tasks/{parent_id}/inline-subtask",
                    data={"content": content}, headers=AJAX)
    return r.json()["task"]["id"]


# ── projects ──────────────────────────────────────────────────────────────────

class TestCreateProject:
    def test_ajax_returns_project_data(self, client):
        r = client.post("/projects/new", data={"name": "Alpha"}, headers=AJAX)
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["project"]["name"] == "Alpha"
        assert "id" in body["project"]

    def test_form_post_redirects_to_projects(self, client):
        r = client.post("/projects/new", data={"name": "Beta"},
                        follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/projects"

    def test_empty_name_returns_failure(self, client):
        r = client.post("/projects/new", data={"name": ""}, headers=AJAX)
        assert r.json()["success"] is False

    def test_multiple_projects_created_independently(self, client):
        id1 = _create_project(client, "P1")
        id2 = _create_project(client, "P2")
        assert id1 != id2


class TestArchiveProject:
    def test_ajax_returns_success(self, client):
        pid = _create_project(client)
        r = client.get(f"/projects/{pid}/delete", headers=AJAX)
        assert r.json()["success"] is True

    def test_also_archives_project_tasks(self, client):
        pid = _create_project(client)
        _add_task(client, pid, "Should be archived")
        client.get(f"/projects/{pid}/delete", headers=AJAX)
        # Archived tasks should NOT appear in the active list
        active = db.get_tasks_by_project(pid, include_archived=False)
        assert len(active) == 0

    def test_form_redirects_to_projects(self, client):
        pid = _create_project(client)
        r = client.get(f"/projects/{pid}/delete", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/projects"


class TestRestoreProject:
    def test_restores_project_and_tasks(self, client):
        pid = _create_project(client)
        _add_task(client, pid, "Task")
        client.get(f"/projects/{pid}/delete", headers=AJAX)  # archive

        r = client.get(f"/projects/{pid}/restore", follow_redirects=False)
        assert r.status_code == 302

        active = db.get_tasks_by_project(pid, include_archived=False)
        assert len(active) == 1


class TestMoveProject:
    def test_reorders_projects(self, client):
        pid1 = _create_project(client, "First")
        pid2 = _create_project(client, "Second")
        r = client.post(f"/projects/{pid2}/move",
                        data={"insert_before_id": str(pid1)}, headers=AJAX)
        assert r.json()["success"] is True

    def test_move_to_end_with_null_sentinel(self, client):
        pid1 = _create_project(client, "First")
        pid2 = _create_project(client, "Second")
        r = client.post(f"/projects/{pid1}/move",
                        data={"insert_before_id": "null"}, headers=AJAX)
        assert r.json()["success"] is True

    def test_form_redirects_to_projects(self, client):
        pid1 = _create_project(client, "A")
        pid2 = _create_project(client, "B")
        r = client.post(f"/projects/{pid2}/move",
                        data={"insert_before_id": str(pid1)},
                        follow_redirects=False)
        assert r.status_code == 302


# ── tasks ─────────────────────────────────────────────────────────────────────

class TestQuickAddTask:
    def test_full_inline_syntax_parsed_correctly(self, client):
        pid = _create_project(client)
        r = client.post(
            f"/projects/{pid}/tasks/quick",
            data={"title": "Fix login [auth] [backend] !critical ~8h >2026-03-01 <2026-03-31"},
            headers=AJAX
        )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        t = body["task"]
        assert t["title"] == "Fix login"
        assert t["priority"] == "critical"
        assert t["effort_hours"] == 8
        assert t["start_date"] == "2026-03-01"
        assert t["due_date"] == "2026-03-31"
        assert "auth" in t["flags"]
        assert "backend" in t["flags"]

    def test_flags_only_title_returns_failure(self, client):
        pid = _create_project(client)
        # Parsed title is empty after flag extraction
        r = client.post(f"/projects/{pid}/tasks/quick",
                        data={"title": "[auth]"}, headers=AJAX)
        assert r.json()["success"] is False

    def test_empty_input_returns_failure(self, client):
        pid = _create_project(client)
        r = client.post(f"/projects/{pid}/tasks/quick",
                        data={"title": ""}, headers=AJAX)
        assert r.json()["success"] is False

    def test_form_post_redirects_to_root(self, client):
        pid = _create_project(client)
        r = client.post(f"/projects/{pid}/tasks/quick",
                        data={"title": "Task"},
                        follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/"

    def test_task_stored_with_correct_project(self, client):
        pid = _create_project(client)
        tid = _add_task(client, pid, "My task")
        task = db.get_task(tid)
        assert task["project_id"] == pid


class TestInlineEditTask:
    def test_updates_title_priority_and_effort(self, client):
        pid = _create_project(client)
        tid = _add_task(client, pid, "Old title")
        r = client.post(f"/tasks/{tid}/inline-edit",
                        data={"content": "New title !major ~3h"},
                        headers=AJAX)
        body = r.json()
        assert body["success"] is True
        assert body["task"]["title"] == "New title"
        assert body["task"]["priority"] == "major"
        assert body["task"]["effort_hours"] == 3

    def test_updates_dates(self, client):
        pid = _create_project(client)
        tid = _add_task(client, pid, "Task")
        r = client.post(f"/tasks/{tid}/inline-edit",
                        data={"content": "Task >2026-04-01 <2026-04-30"},
                        headers=AJAX)
        t = r.json()["task"]
        assert t["start_date"] == "2026-04-01"
        assert t["due_date"] == "2026-04-30"

    def test_adds_new_flag(self, client):
        pid = _create_project(client)
        tid = _add_task(client, pid, "Task")
        r = client.post(f"/tasks/{tid}/inline-edit",
                        data={"content": "Task [new-flag]"},
                        headers=AJAX)
        assert "new-flag" in r.json()["task"]["flags"]

    def test_removes_old_flag_and_adds_new(self, client):
        pid = _create_project(client)
        tid = _add_task(client, pid, "Task [old-flag]")
        r = client.post(f"/tasks/{tid}/inline-edit",
                        data={"content": "Task [new-flag]"},
                        headers=AJAX)
        task = r.json()["task"]
        assert "new-flag" in task["flags"]
        assert "old-flag" not in task["flags"]

    def test_nonexistent_task_returns_failure(self, client):
        r = client.post("/tasks/99999/inline-edit",
                        data={"content": "Anything"},
                        headers=AJAX)
        body = r.json()
        assert body["success"] is False
        assert "error" in body

    def test_form_post_redirects(self, client):
        pid = _create_project(client)
        tid = _add_task(client, pid, "Task")
        r = client.post(f"/tasks/{tid}/inline-edit",
                        data={"content": "Updated"},
                        follow_redirects=False)
        assert r.status_code == 302


class TestInlineSubtask:
    def test_creates_subtask_with_correct_parent_and_level(self, client):
        pid = _create_project(client)
        parent_id = _add_task(client, pid, "Parent")
        r = client.post(f"/tasks/{parent_id}/inline-subtask",
                        data={"content": "Child task !major"},
                        headers=AJAX)
        body = r.json()
        assert body["success"] is True
        child = body["task"]
        assert child["parent_id"] == parent_id
        assert child["title"] == "Child task"
        assert child["priority"] == "major"
        assert child["level"] == 1

    def test_depth_limit_at_level_4_returns_failure(self, client):
        pid = _create_project(client)
        # Build a chain level 0 → 1 → 2 → 3
        tid = _add_task(client, pid, "Level 0")
        tid = _add_subtask(client, tid, "Level 1")
        tid = _add_subtask(client, tid, "Level 2")
        tid = _add_subtask(client, tid, "Level 3")

        # Level 4 must be rejected
        r = client.post(f"/tasks/{tid}/inline-subtask",
                        data={"content": "Level 4 — too deep"},
                        headers=AJAX)
        body = r.json()
        assert body["success"] is False
        assert "depth" in body.get("error", "").lower()

    def test_nonexistent_parent_returns_failure(self, client):
        r = client.post("/tasks/99999/inline-subtask",
                        data={"content": "Orphan"},
                        headers=AJAX)
        assert r.json()["success"] is False

    def test_subtask_inherits_project_id(self, client):
        pid = _create_project(client)
        parent_id = _add_task(client, pid, "Parent")
        child_id = _add_subtask(client, parent_id, "Child")
        task = db.get_task(child_id)
        assert task["project_id"] == pid


class TestToggleTask:
    def test_marks_incomplete_task_complete(self, client):
        pid = _create_project(client)
        tid = _add_task(client, pid)
        r = client.get(f"/tasks/{tid}/toggle", headers=AJAX)
        body = r.json()
        assert body["success"] is True
        assert body["completed_at"] is not None
        assert tid in body["affected_ids"]

    def test_unmarks_completed_task(self, client):
        pid = _create_project(client)
        tid = _add_task(client, pid)
        client.get(f"/tasks/{tid}/toggle", headers=AJAX)  # mark done
        r = client.get(f"/tasks/{tid}/toggle", headers=AJAX)  # undo
        assert r.json()["completed_at"] is None

    def test_completion_cascades_to_incomplete_subtasks(self, client):
        pid = _create_project(client)
        parent_id = _add_task(client, pid, "Parent")
        child_id = _add_subtask(client, parent_id, "Child")

        r = client.get(f"/tasks/{parent_id}/toggle", headers=AJAX)
        body = r.json()
        assert parent_id in body["affected_ids"]
        assert child_id in body["affected_ids"]

    def test_undo_reverts_same_timestamp_subtasks(self, client):
        pid = _create_project(client)
        parent_id = _add_task(client, pid, "Parent")
        child_id = _add_subtask(client, parent_id, "Child")

        # Complete together
        client.get(f"/tasks/{parent_id}/toggle", headers=AJAX)
        # Undo: child was completed with same timestamp → should be reverted
        r = client.get(f"/tasks/{parent_id}/toggle", headers=AJAX)
        body = r.json()
        assert parent_id in body["affected_ids"]
        assert child_id in body["affected_ids"]
        assert body["completed_at"] is None

    def test_undo_does_not_revert_independently_completed_subtask(self, client):
        pid = _create_project(client)
        parent_id = _add_task(client, pid, "Parent")
        child_id = _add_subtask(client, parent_id, "Child")

        # Complete child independently first (different timestamp)
        client.get(f"/tasks/{child_id}/toggle", headers=AJAX)
        # Complete parent — child already done, so it is NOT included in cascade
        r = client.get(f"/tasks/{parent_id}/toggle", headers=AJAX)
        assert child_id not in r.json()["affected_ids"]

        # Undo parent — child should NOT be reverted (different timestamp)
        r = client.get(f"/tasks/{parent_id}/toggle", headers=AJAX)
        assert child_id not in r.json()["affected_ids"]
        # Child must still be completed
        assert db.get_task(child_id)["completed_at"] is not None

    def test_form_get_redirects(self, client):
        pid = _create_project(client)
        tid = _add_task(client, pid)
        r = client.get(f"/tasks/{tid}/toggle", follow_redirects=False)
        assert r.status_code == 302


class TestArchiveTask:
    def test_archives_task_and_all_subtasks(self, client):
        pid = _create_project(client)
        parent_id = _add_task(client, pid, "Parent")
        child_id = _add_subtask(client, parent_id, "Child")
        grandchild_id = _add_subtask(client, child_id, "Grandchild")

        r = client.get(f"/tasks/{parent_id}/archive", headers=AJAX)
        body = r.json()
        assert body["success"] is True
        assert parent_id in body["archived_ids"]
        assert child_id in body["archived_ids"]
        assert grandchild_id in body["archived_ids"]

    def test_archived_tasks_excluded_from_active_list(self, client):
        pid = _create_project(client)
        tid = _add_task(client, pid, "Task")
        client.get(f"/tasks/{tid}/archive", headers=AJAX)
        active = db.get_tasks_by_project(pid, include_archived=False)
        assert all(t["id"] != tid for t in active)

    def test_form_get_redirects(self, client):
        pid = _create_project(client)
        tid = _add_task(client, pid)
        r = client.get(f"/tasks/{tid}/archive", follow_redirects=False)
        assert r.status_code == 302


class TestRestoreTask:
    def test_restores_task_and_all_subtasks(self, client):
        pid = _create_project(client)
        parent_id = _add_task(client, pid, "Parent")
        child_id = _add_subtask(client, parent_id, "Child")

        client.get(f"/tasks/{parent_id}/archive", headers=AJAX)
        r = client.get(f"/tasks/{parent_id}/restore", headers=AJAX)
        body = r.json()
        assert body["success"] is True
        assert parent_id in body["restored_ids"]
        assert child_id in body["restored_ids"]

    def test_restored_task_appears_in_active_list(self, client):
        pid = _create_project(client)
        tid = _add_task(client, pid, "Task")
        client.get(f"/tasks/{tid}/archive", headers=AJAX)
        client.get(f"/tasks/{tid}/restore", headers=AJAX)
        active = db.get_tasks_by_project(pid, include_archived=False)
        assert any(t["id"] == tid for t in active)

    def test_form_get_redirects(self, client):
        pid = _create_project(client)
        tid = _add_task(client, pid)
        client.get(f"/tasks/{tid}/archive", headers=AJAX)
        r = client.get(f"/tasks/{tid}/restore", follow_redirects=False)
        assert r.status_code == 302


class TestMoveTask:
    def test_moves_task_under_new_parent(self, client):
        pid = _create_project(client)
        task_a = _add_task(client, pid, "Task A")
        task_b = _add_task(client, pid, "Task B")

        r = client.post(f"/tasks/{task_b}/move",
                        data={"parent_id": str(task_a), "insert_before_id": "null"},
                        headers=AJAX)
        body = r.json()
        assert body["success"] is True
        assert body["task"]["parent_id"] == task_a
        assert body["task"]["level"] == 1

    def test_reorders_root_siblings(self, client):
        pid = _create_project(client)
        task_a = _add_task(client, pid, "A")
        task_b = _add_task(client, pid, "B")
        task_c = _add_task(client, pid, "C")

        # Move C before A
        r = client.post(f"/tasks/{task_c}/move",
                        data={"parent_id": "null", "insert_before_id": str(task_a)},
                        headers=AJAX)
        assert r.json()["success"] is True

    def test_subtask_level_updated_on_move(self, client):
        pid = _create_project(client)
        parent = _add_task(client, pid, "Parent")
        child = _add_subtask(client, parent, "Child")  # level 1

        # Move child to root level
        r = client.post(f"/tasks/{child}/move",
                        data={"parent_id": "null", "insert_before_id": "null"},
                        headers=AJAX)
        assert r.json()["task"]["level"] == 0

    def test_move_rejected_when_it_would_exceed_depth(self, client):
        pid = _create_project(client)
        l0 = _add_task(client, pid, "L0")
        l1 = _add_subtask(client, l0, "L1")
        l2 = _add_subtask(client, l1, "L2")
        l3 = _add_subtask(client, l2, "L3")  # level 3

        # Moving l0 under l3 would put l0 at level 4 → rejected
        r = client.post(f"/tasks/{l0}/move",
                        data={"parent_id": str(l3), "insert_before_id": "null"},
                        headers=AJAX)
        assert r.json()["success"] is False

    def test_form_post_redirects(self, client):
        pid = _create_project(client)
        task_a = _add_task(client, pid, "A")
        task_b = _add_task(client, pid, "B")
        r = client.post(f"/tasks/{task_b}/move",
                        data={"parent_id": "null", "insert_before_id": str(task_a)},
                        follow_redirects=False)
        assert r.status_code == 302


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags:
    def test_flags_page_lists_all_flags(self, client):
        pid = _create_project(client)
        _add_task(client, pid, "Task [alpha] [beta]")
        r = client.get("/flags")
        assert r.status_code == 200
        assert "alpha" in r.text
        assert "beta" in r.text

    def test_delete_flag_ajax_returns_success(self, client):
        pid = _create_project(client)
        _add_task(client, pid, "Task [to-delete]")
        flag = next(f for f in db.get_all_flags() if f["name"] == "to-delete")
        r = client.get(f"/flags/{flag['id']}/delete", headers=AJAX)
        assert r.json()["success"] is True

    def test_delete_flag_removes_it_from_db(self, client):
        pid = _create_project(client)
        _add_task(client, pid, "Task [gone]")
        flag = next(f for f in db.get_all_flags() if f["name"] == "gone")
        client.get(f"/flags/{flag['id']}/delete", headers=AJAX)
        assert not any(f["name"] == "gone" for f in db.get_all_flags())

    def test_delete_flag_form_redirects(self, client):
        pid = _create_project(client)
        _add_task(client, pid, "Task [temp]")
        flag = next(f for f in db.get_all_flags() if f["name"] == "temp")
        r = client.get(f"/flags/{flag['id']}/delete", follow_redirects=False)
        assert r.status_code == 302


# ── page smoke tests ──────────────────────────────────────────────────────────

class TestPages:
    def test_index_page(self, client):
        assert client.get("/").status_code == 200

    def test_projects_page(self, client):
        assert client.get("/projects").status_code == 200

    def test_archive_page(self, client):
        assert client.get("/archive").status_code == 200

    def test_flags_page(self, client):
        assert client.get("/flags").status_code == 200

    def test_index_page_with_projects_and_tasks(self, client):
        pid = _create_project(client, "My Project")
        _add_task(client, pid, "Task One")
        r = client.get("/")
        assert r.status_code == 200
        assert "My Project" in r.text
        assert "Task One" in r.text
