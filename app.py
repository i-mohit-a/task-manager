import sys
from starlette.applications import Starlette
from starlette.responses import RedirectResponse, JSONResponse
from starlette.routing import Route
from starlette.templating import Jinja2Templates
from pathlib import Path

import database as db


def is_ajax(request):
    """Check if request is AJAX."""
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest" or
        "application/json" in request.headers.get("Accept", "")
    )


def task_to_dict(task):
    """Convert task row to dict with flag colors."""
    flags_list = task["flags"].split(",") if task["flags"] else []
    return {
        "id": task["id"],
        "project_id": task["project_id"],
        "parent_id": task["parent_id"],
        "title": task["title"],
        "priority": task["priority"],
        "effort_hours": task["effort_hours"],
        "level": task["level"],
        "created_at": task["created_at"],
        "completed_at": task["completed_at"],
        "start_date": task["start_date"],
        "due_date": task["due_date"],
        "flags": task["flags"] or "",
        "flags_list": [{"name": f, "color": flag_color(f)} for f in flags_list if f]
    }


def get_templates_dir():
    """Get templates directory, works both in dev and bundled app."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent / "templates"
    return Path(__file__).parent / "templates"


templates = Jinja2Templates(directory=get_templates_dir())


def flag_color(flag_name):
    """Return a consistent color index (0-7) for a flag name."""
    return sum(ord(c) for c in flag_name) % 8


templates.env.filters["flag_color"] = flag_color


async def index(request):
    projects = db.get_all_projects()
    task_trees = {}
    for project in projects:
        tasks = db.get_tasks_by_project(project["id"])
        task_trees[project["id"]] = db.build_task_tree(tasks)
    return templates.TemplateResponse(
        request,
        "index.html",
        {"projects": projects, "task_trees": task_trees}
    )


async def projects_page(request):
    projects = db.get_all_projects()
    return templates.TemplateResponse(
        request,
        "projects.html",
        {"projects": projects}
    )


async def create_project(request):
    form = await request.form()
    name = form.get("name", "").strip()
    project_id = None
    if name:
        project_id = db.create_project(name)
    if is_ajax(request):
        if project_id:
            project = db.get_project(project_id)
            return JSONResponse({"success": True, "project": dict(project)})
        return JSONResponse({"success": False})
    return RedirectResponse(url="/projects", status_code=302)


async def delete_project(request):
    project_id = int(request.path_params["project_id"])
    db.archive_project(project_id)
    if is_ajax(request):
        return JSONResponse({"success": True})
    return RedirectResponse(url="/projects", status_code=302)


async def quick_add_task(request):
    project_id = int(request.path_params["project_id"])
    form = await request.form()
    raw_input = form.get("title", "").strip()
    task_id = None
    if raw_input:
        parsed = db.parse_task_input(raw_input)
        if parsed["title"]:
            task_id = db.create_task(
                project_id,
                parsed["title"],
                parsed["priority"],
                parsed["effort_hours"],
                start_date=parsed["start_date"],
                due_date=parsed["due_date"]
            )
            for flag in parsed["flags"]:
                db.add_flag_to_task(task_id, flag)
    if is_ajax(request):
        if task_id:
            task = db.get_task(task_id)
            return JSONResponse({"success": True, "task": task_to_dict(task)})
        return JSONResponse({"success": False})

    return RedirectResponse(url="/", status_code=302)


async def inline_edit_task(request):
    task_id = int(request.path_params["task_id"])
    task = db.get_task(task_id)
    if not task:
        if is_ajax(request):
            return JSONResponse({"success": False, "error": "Task not found"})
        return RedirectResponse(url="/", status_code=302)

    form = await request.form()
    raw_input = form.get("content", "").strip()
    if raw_input:
        parsed = db.parse_task_input(raw_input)
        if parsed["title"]:
            db.update_task(
                task_id,
                title=parsed["title"],
                priority=parsed["priority"],
                effort_hours=parsed["effort_hours"],
                start_date=parsed["start_date"],
                due_date=parsed["due_date"]
            )
            current_flags = set(task["flags"].split(",") if task["flags"] else set())
            new_flags = set(parsed["flags"])
            for flag in current_flags - new_flags:
                db.remove_flag_from_task(task_id, flag)
            for flag in new_flags - current_flags:
                db.add_flag_to_task(task_id, flag)

    if is_ajax(request):
        updated_task = db.get_task(task_id)
        return JSONResponse({"success": True, "task": task_to_dict(updated_task)})
    return RedirectResponse(url="/", status_code=302)


async def inline_subtask(request):
    parent_id = int(request.path_params["task_id"])
    parent_task = db.get_task(parent_id)
    if not parent_task:
        if is_ajax(request):
            return JSONResponse({"success": False, "error": "Parent task not found"})
        return RedirectResponse(url="/", status_code=302)

    form = await request.form()
    raw_input = form.get("content", "").strip()
    task_id = None
    if raw_input:
        parsed = db.parse_task_input(raw_input)
        if parsed["title"]:
            try:
                task_id = db.create_task(
                    parent_task["project_id"],
                    parsed["title"],
                    parsed["priority"],
                    parsed["effort_hours"],
                    parent_id
                )
                for flag in parsed["flags"]:
                    db.add_flag_to_task(task_id, flag)
            except ValueError:
                if is_ajax(request):
                    return JSONResponse({"success": False, "error": "Maximum subtask depth reached"})
    if is_ajax(request):
        if task_id:
            task = db.get_task(task_id)
            return JSONResponse({"success": True, "task": task_to_dict(task)})
        return JSONResponse({"success": False})

    return RedirectResponse(url="/", status_code=302)


async def toggle_task(request):
    task_id = int(request.path_params["task_id"])
    affected_ids = db.toggle_task_complete(task_id)

    if is_ajax(request):
        task = db.get_task(task_id)
        return JSONResponse({
            "success": True,
            "task_id": task_id,
            "completed_at": task["completed_at"] if task else None,
            "affected_ids": affected_ids
        })

    return RedirectResponse(url="/", status_code=302)


async def archive_task(request):
    task_id = int(request.path_params["task_id"])
    archived_ids = db.archive_task(task_id)

    if is_ajax(request):
        return JSONResponse({"success": True, "task_id": task_id, "archived_ids": archived_ids})

    return RedirectResponse(url="/", status_code=302)


async def flags_list(request):
    flags = db.get_all_flags()
    return templates.TemplateResponse(
        request,
        "flags.html",
        {"flags": flags}
    )


async def delete_flag(request):
    flag_id = int(request.path_params["flag_id"])
    db.delete_flag(flag_id)
    if is_ajax(request):
        return JSONResponse({"success": True})
    return RedirectResponse(url="/flags", status_code=302)


async def archive_page(request):
    projects = db.get_all_projects()
    archived_projects = db.get_archived_projects()
    archived_trees = {}
    has_archived = False
    for project in projects:
        tasks = db.get_archived_tasks_by_project(project["id"])
        if tasks:
            has_archived = True
            archived_trees[project["id"]] = db.build_task_tree(tasks)
    for project in archived_projects:
        tasks = db.get_tasks_by_project(project["id"], include_archived=True)
        has_archived = True
        archived_trees[project["id"]] = db.build_task_tree(tasks)
    return templates.TemplateResponse(
        request,
        "archive.html",
        {
            "projects": projects,
            "archived_projects": archived_projects,
            "archived_trees": archived_trees,
            "has_archived": has_archived
        }
    )


async def move_project(request):
    project_id = int(request.path_params["project_id"])
    form = await request.form()
    insert_before_id = form.get("insert_before_id")
    insert_before_id = int(insert_before_id) if insert_before_id and insert_before_id != "null" else None
    success = db.move_project(project_id, insert_before_id)
    if is_ajax(request):
        return JSONResponse({"success": success})
    return RedirectResponse(url="/projects", status_code=302)


async def restore_project(request):
    project_id = int(request.path_params["project_id"])
    db.restore_project(project_id)
    return RedirectResponse(url="/archive", status_code=302)


async def restore_task(request):
    task_id = int(request.path_params["task_id"])
    restored_ids = db.restore_task(task_id)

    if is_ajax(request):
        return JSONResponse({"success": True, "task_id": task_id, "restored_ids": restored_ids})

    return RedirectResponse(url="/archive", status_code=302)


async def move_task(request):
    task_id = int(request.path_params["task_id"])
    form = await request.form()
    new_parent_id = form.get("parent_id")
    new_parent_id = int(new_parent_id) if new_parent_id and new_parent_id != "null" else None
    insert_before_id = form.get("insert_before_id")
    insert_before_id = int(insert_before_id) if insert_before_id and insert_before_id != "null" else None

    success = db.move_task(task_id, new_parent_id, insert_before_id)

    if is_ajax(request):
        if success:
            task = db.get_task(task_id)
            return JSONResponse({"success": True, "task": task_to_dict(task)})
        return JSONResponse({"success": False, "error": "Cannot move task"})

    return RedirectResponse(url="/", status_code=302)


routes = [
    Route("/", index),
    Route("/projects", projects_page),
    Route("/projects/new", create_project, methods=["POST"]),
    Route("/projects/{project_id:int}/delete", delete_project),
    Route("/projects/{project_id:int}/restore", restore_project),
    Route("/projects/{project_id:int}/move", move_project, methods=["POST"]),
    Route("/projects/{project_id:int}/tasks/quick", quick_add_task, methods=["POST"]),
    Route("/tasks/{task_id:int}/inline-edit", inline_edit_task, methods=["POST"]),
    Route("/tasks/{task_id:int}/inline-subtask", inline_subtask, methods=["POST"]),
    Route("/tasks/{task_id:int}/toggle", toggle_task),
    Route("/tasks/{task_id:int}/archive", archive_task),
    Route("/tasks/{task_id:int}/restore", restore_task),
    Route("/tasks/{task_id:int}/move", move_task, methods=["POST"]),
    Route("/flags", flags_list),
    Route("/flags/{flag_id:int}/delete", delete_flag),
    Route("/archive", archive_page),
]

app = Starlette(routes=routes, on_startup=[db.init_db])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
