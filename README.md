# Task Manager

A keyboard-driven local task manager built with Python (Starlette) and SQLite. Runs as a background service accessible via browser at a local domain.

---

## Requirements

- macOS (uses launchd for production background service)
- Python 3.8+
- Caddy (reverse proxy for local domain routing)

```bash
brew install caddy
```

---

## Project Structure

```
task-manager/
├── app.py                # Starlette web app, routes, AJAX handlers
├── database.py           # SQLite layer, migrations, task tree building
├── task_parser.py        # Parses inline task syntax
├── requirements.txt      # Python dependencies
├── deploy.sh             # Dev and production deployment script
└── templates/
    ├── base.html         # Layout, CSS, settings UI
    ├── index.html        # Main task view and keyboard navigation JS
    ├── projects.html     # Project management
    ├── flags.html        # Flag listing and deletion
    └── archive.html      # Archived tasks and projects
```

---

## Quick Start (Dev)

```bash
git clone https://github.com/i-mohit-a/task-manager.git
cd task-manager
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
./deploy.sh --dev --start
```

On first run, `deploy.sh` adds entries to `/etc/hosts` and prompts for your sudo password once.

Open: http://dev.taskmanager.local

```bash
./deploy.sh --dev --stop       # stop
./deploy.sh --dev --restart    # restart
```

---

## Production Deploy

```bash
./deploy.sh --prd
```

This will:

- Add `/etc/hosts` entries (prompts for sudo once if not already set)
- Copy all app files to `~/.local/taskmanager/`
- Create a virtual environment and install dependencies (first run only)
- Install a launchd LaunchAgent for the app (auto-starts at login)
- Install a launchd LaunchAgent for Caddy (auto-starts at login)
- Back up the previous version before updating
- Start both services

Open: http://taskmanager.local

```bash
./deploy.sh --prd --restart    # restart without redeploying
```

Logs:

```bash
cat /tmp/taskmanager.log
cat /tmp/taskmanager.err
cat /tmp/taskmanager-caddy.log
```

---

## URLs and Ports

Both modes can run simultaneously. Caddy routes each domain to the correct port.

| Mode       | URL                          | Internal port |
|------------|------------------------------|---------------|
| Dev        | http://dev.taskmanager.local | 8001          |
| Production | http://taskmanager.local     | 8000          |

---

## Pages

| Page    | Path       |
|---------|------------|
| Tasks   | `/`        |
| Projects | `/projects` |
| Flags   | `/flags`   |
| Archive | `/archive` |

---

## Database

| Mode        | Location                                               |
|-------------|--------------------------------------------------------|
| Dev         | `tasks.db` in project directory                        |
| Production  | `~/Library/Application Support/TaskManager/tasks.db`  |

Schema is auto-created on first run. Migrations are applied automatically on startup.

---

## Features

### Projects

Tasks are organised into projects. Each project has its own task list on the home page with a quick-add input.

- Create projects from the Projects page or using the quick-add at the bottom of the project list
- Archive a project from the Projects page — this also archives all its tasks
- Archived projects and their tasks can be restored from the Archive page
- Projects can be reordered; order persists across reloads
- Both dev and production databases are kept separate

---

### Tasks

Each task belongs to a project and can have:

- a title
- a priority: `critical`, `major`, or `minor` (default: `minor`)
- an effort estimate in hours (e.g. `~4h` or `~1.5h`)
- a start date and a due date
- one or more flags (tags)
- subtasks (up to 3 levels deep)

Tasks display a one-letter priority badge, any flag badges, the title, effort, dates, and the creation date. Completed tasks show the completion date instead. Incomplete tasks always appear above completed tasks within their list.

---

### Task Input Syntax

All task fields can be set in a single text input when adding or editing a task:

```
task title [flag1] [flag2] !priority ~Nh >YYYY-MM-DD <YYYY-MM-DD
```

| Part       | Syntax      | Example          | Notes                              |
|------------|-------------|------------------|------------------------------------|
| Title      | plain text  | `Fix signup bug` | anything not matched by other tokens |
| Flag       | `[name]`    | `[auth]`         | any word in brackets; multiple allowed |
| Priority   | `!level`    | `!critical`      | critical, major, or minor; default is minor |
| Effort     | `~Nh`       | `~4h` `~1.5h`    | hours prefixed with `~`            |
| Start date | `>date`     | `>2026-03-15`    | YYYY-MM-DD format                  |
| Due date   | `<date`     | `<2026-03-31`    | YYYY-MM-DD format                  |

Token order does not matter. Example:

```
Fix signup bug [auth] [backend] !critical ~2h >2026-03-10 <2026-03-15
```

---

### Subtasks

Tasks can have subtasks up to 3 levels deep (level 0 is root).

- Press `ss` on any non-maximum-depth task to add a subtask inline
- Subtasks are indented visually under their parent
- Completing a parent also completes all its incomplete subtasks, stamped with the same timestamp
- Undoing a parent reverts only subtasks completed at that same timestamp
- Archiving or restoring a task also archives or restores all its subtasks

---

### Completing Tasks

Toggle done or undone via `dd` or clicking `[done]` / `[undo]`.

When marked done, the task moves to the bottom of the list and the completion date is shown. Undoing restores it above completed tasks.

---

### Editing Tasks

Press `ee` or click `[edit]` to edit a task inline. All current values are pre-filled in the same input syntax. Press Enter to save, Escape to cancel.

Flags not present in the edited input are removed; new flags are added automatically.

---

### Flags

Flags are free-form tags applied to tasks. Each flag name gets a consistent colour (hash-based, 8 colour options) shown as a small badge on the task row.

- Add flags using `[flagname]` in the task input
- Multiple flags per task are allowed
- Remove a flag by editing the task and omitting it
- All flags are listed on the Flags page (`/flags`)
- Flags can be deleted from the Flags page — deletion removes the flag from all tasks
- Flags are shared across all projects

---

### Archiving

Press `xx` or click `[x]` to archive a task. Archived tasks are removed from the main view but not deleted.

- Archiving a task also archives all its subtasks
- Archived tasks appear at `/archive`, grouped by project
- Click `[restore]` on the archive page to restore a task and all its subtasks

---

### Sorting

Each project header has three sort controls:

- `[sort:priority]` — sorts by priority (critical first), completed tasks last
- `[sort:effort]` — sorts by total effort hours (highest first), completed tasks last
- `[sort:tag]` — prompts for a flag name, floats tasks with that flag to the top

Sorting is client-side only and does not persist on reload.

---

### Moving Tasks

Press `alt+up` / `alt+down` to reorder tasks. Positions persist across reloads.

Moving within the same level swaps with the sibling above or below.

Moving across levels:

- Moving up into a subtree makes the task the last child of that subtree, one level per keypress
- Moving down at the bottom of a subtree de-nests the task one level, placing it after its parent
- Moving up at the top of a subtree de-nests the task one level, placing it before its parent

Tasks cannot be moved across projects. Tasks carry their subtrees when moved.

---

### Multi-Select

Hold `shift+up` / `shift+down` to extend the selection across multiple tasks. Selected rows are highlighted. `alt+up` / `alt+down` moves all selected tasks together.

Press Escape to clear the selection.

---

### Quick Add

Each project on the home page has a quick-add input positioned just above any completed tasks. Press `nn` to focus it, or press the down arrow when on the last incomplete task.

Type using the inline syntax and press Enter to add. The input auto-grows for long text. Press Escape to clear and dismiss.

---

### Settings

A settings panel in the top-right corner (gear icon) provides two toggles, both persisted in localStorage:

- Font size — compact mode reduces the UI to a smaller font
- Task lines — show a dotted separator line under each task row

Hovering over a task row always shows the separator line regardless of the setting.

---

### Keyboard Shortcuts

All shortcuts work when no input is focused. Double-key shortcuts (`dd`, `ee`, `ss`, `xx`, `nn`) require both keypresses within 500ms.

Home page:

| Key              | Action                                   |
|------------------|------------------------------------------|
| up / down        | Move cursor                              |
| Home             | Jump to first task                       |
| End              | Jump to last task                        |
| shift + up/down  | Extend selection                         |
| alt + up/down    | Move task up or down (persisted)         |
| dd               | Toggle task done / undone                |
| ee               | Edit task inline                         |
| ss               | Add subtask                              |
| xx               | Archive task                             |
| nn               | Focus quick-add for current project      |
| Escape           | Clear selection, cancel edit or subtask  |

Projects page:

| Key              | Action                                   |
|------------------|------------------------------------------|
| up / down        | Move cursor                              |
| shift + up/down  | Extend selection                         |
| alt + up/down    | Reorder selected projects (persisted)    |
| nn               | Focus new project input                  |
| xx               | Archive project at cursor                |
