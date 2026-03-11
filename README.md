# Task Manager

A keyboard-driven local task manager built with Python (Starlette) and SQLite. Runs as a background service accessible via browser at `http://127.0.0.1:8000`.

---

## Project Structure

```
task-manager-v0/
├── app.py                        # Starlette web app, routes
├── database.py                   # SQLite database layer
├── requirements.txt              # Python dependencies
├── deploy.sh                     # Single script for local dev and production deploy
├── com.local.taskmanager.plist   # macOS LaunchAgent (auto-start at login)
└── templates/
    ├── base.html                 # Base layout + CSS
    ├── index.html                # Main task view + keyboard JS
    ├── archive.html              # Archived tasks
    ├── flags.html                # Flag listing
    └── projects.html             # Project management
```

---

## Setup (first time)

### 1. Create and activate a virtual environment

```bash
cd task-manager-v0
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

---

## Running the App

All server control goes through `deploy.sh`.

### Local / Dev

Start the server in the background from the project folder:

```bash
./deploy.sh --dev --start
```

Stop it:

```bash
./deploy.sh --dev --stop
```

`--dev` mode automatically sets `TASKMANAGER_DEV=1`, so the database is stored locally in the project folder as `tasks.db`.

Logs are written to:
- `/tmp/taskmanager.log` — stdout
- `/tmp/taskmanager.err` — stderr

Open the app at http://127.0.0.1:8000

---

### Production (macOS background service)

Deploys to `~/.local/taskmanager/` and installs a launchd LaunchAgent that auto-starts at login and keeps the server alive.

```bash
./deploy.sh --prd
```

This will:
- Stop the existing service if running
- Back up current installed files
- Copy all app files to `~/.local/taskmanager/`
- Create a virtual environment and install dependencies (first run only)
- Install the LaunchAgent plist to `~/Library/LaunchAgents/` (first run only)
- Start the service via launchd

Open the app at http://127.0.0.1:8000

To manage the production service manually:

```bash
# Stop
launchctl unload ~/Library/LaunchAgents/com.local.taskmanager.plist

# Start
launchctl load ~/Library/LaunchAgents/com.local.taskmanager.plist

# View logs
cat /tmp/taskmanager.log
cat /tmp/taskmanager.err
```

---

## Database

| Mode | Location |
|------|----------|
| Default | `~/Library/Application Support/TaskManager/tasks.db` |
| Dev (with `TASKMANAGER_DEV=1`) | `tasks.db` in project directory |

Schema is auto-created on first run. Migrations are applied automatically on startup.

---

## Pages

| Page | URL |
|------|-----|
| Tasks (home) | http://127.0.0.1:8000/ |
| Projects | http://127.0.0.1:8000/projects |
| Flags | http://127.0.0.1:8000/flags |
| Archive | http://127.0.0.1:8000/archive |

---

## Features

### Projects

Tasks are organised into projects. Each project has its own task list and quick-add bar on the home page.

- Create a project from the Projects page by typing a name and pressing Enter.
- Delete a project from the Projects page. Deleting a project permanently removes all its tasks and subtasks.
- Projects are listed in reverse creation order on the home page.

---

### Tasks

Each task belongs to a project and can have:

- a title
- a priority: `critical`, `major`, or `minor` (default: `minor`)
- an effort estimate in hours
- a start date
- a due date
- one or more flags (tags)
- subtasks (up to 3 levels deep)

Tasks are displayed with a one-letter priority badge (`c`, `m`, or `m`), followed by any flags, the title, and then the effort and dates as muted metadata. The creation date is always shown. When completed, the completion date is shown instead.

Incomplete tasks appear before completed tasks within each list. Within each group the order is the manually set position (persisted across reloads).

---

### Task Input Syntax

All task fields can be set inline when adding or editing a task using a single text input. The syntax is:

```
task title [flag1] [flag2] !priority ~Nh >YYYY-MM-DD <YYYY-MM-DD
```

| Part | Syntax | Example | Notes |
|------|--------|---------|-------|
| Title | plain text | `Fix signup bug` | everything not matched by other tokens |
| Flag | `[name]` | `[auth]` `[backend]` | any word in brackets; multiple allowed |
| Priority | `!critical` `!major` `!minor` | `!critical` | prefix with `!`; omit for default `minor` |
| Effort | `~Nh` | `~4h` | hours prefixed with `~` |
| Start date | `>YYYY-MM-DD` | `>2026-03-15` | shown as `>date` in the task row |
| Due date | `<YYYY-MM-DD` | `<2026-03-31` | shown as `<date` in the task row |

Example: `Fix signup bug [auth] [backend] !critical ~2h >2026-03-10 <2026-03-15`

The order of tokens does not matter. Any unrecognised text becomes the title.

---

### Subtasks

A task can have subtasks up to 3 levels deep (level 0 is root, level 3 is maximum depth).

- Add a subtask by pressing `ss` on any task that is not at level 3.
- Subtasks are indented visually under their parent.
- Completing a parent task also completes all its incomplete subtasks, stamped with the same timestamp so they can be undone together.
- Undoing a parent task reverts only the subtasks that were completed at the same timestamp as the parent.
- Archiving or restoring a task also archives or restores all its subtasks.

---

### Completing Tasks

Toggle a task done or undone:

- Click `[done]` / `[undo]` on the task row, or
- Press `dd` with the cursor on the task.

When marked done, the task moves to the bottom of the list and the completion date is shown. Pressing `dd` again (or clicking `[undo]`) restores it to incomplete.

---

### Editing Tasks

Press `ee` or click `[edit]` to edit a task inline. The current task values are pre-filled in the same input syntax as task creation. Edit the text and press Enter to save, or Escape to cancel.

Editing supports all fields: title, flags, priority, effort, start date, and due date. Flags not present in the new input are removed; new flags are added.

---

### Flags

Flags are free-form tags applied to tasks. Each flag gets a consistent colour derived from its name, shown as a small badge on the task row. The same flag name always gets the same colour.

- Add flags using `[flagname]` in the task input when creating or editing.
- Multiple flags are allowed per task.
- Remove a flag by editing the task and omitting it from the input.
- All flags currently in use are listed on the Flags page (`/flags`).
- Flags are shared across all projects.

---

### Archiving

Archive a task to remove it from the main view without deleting it.

- Press `xx` or click `[x]` on the task row.
- Archiving a task also archives all its subtasks.
- Archived tasks are visible at `/archive`, grouped by project.
- Restore a task from the archive page by clicking `restore`. Restoring also restores all subtasks.

---

### Sorting

Each project header has three sort controls: `[sort:priority]`, `[sort:effort]`, and `[sort:tag]`.

- `sort:priority` — sorts tasks by their highest priority (critical first, then major, then minor), with completed tasks always last.
- `sort:effort` — sorts tasks by total effort (highest first), with completed tasks always last.
- `sort:tag` — prompts for a flag name and sorts tasks that have that flag to the top.

Sorting is visual only and does not persist on reload. It only sorts root-level tasks within a project.

---

### Moving Tasks

Press `alt + up` or `alt + down` to reorder tasks. Moved positions are persisted to the database and survive page reloads.

Moving within the same level swaps the task with its sibling above or below.

Moving up into a subtree:
- If the task immediately above belongs to a subtree (i.e. is a subtask), the moving task enters that subtree as the last child, one level at a time per keypress. Pressing alt-up repeatedly moves it further up through the nested levels.

Moving down out of a parent (de-nesting):
- If the task is a subtask and there is nothing below it within its current parent, pressing alt-down moves it out one level, placing it immediately after the parent. Each press de-nests one level. After reaching root level, alt-down moves it below the next sibling as normal.

Moving up out of a parent (de-nesting):
- If the task is a subtask and there is nothing above it within its current parent, pressing alt-up moves it out one level and places it immediately before the parent. Each press de-nests one level and moves it above the former parent.

Tasks cannot be moved across projects. Tasks with subtasks carry their subtrees when moved.

---

### Multi-select

Hold `shift + up` or `shift + down` to extend the selection to multiple tasks. Selected rows are highlighted. Actions such as alt-move apply to the whole selection.

Press `Escape` to clear the selection.

---

### Quick Add

Each project on the home page has a quick-add input below its task list. Click it or press `nn` (when cursor is on a task in that project) to focus it.

Type a task using the inline syntax and press Enter to add it. The new task appears at the top of the incomplete tasks. Press Escape to clear the input and blur it.

---

### Keyboard Shortcuts

All shortcuts are available when no input is focused.

| Key | Action |
|-----|--------|
| `j` or `down arrow` | Move cursor down |
| `k` or `up arrow` | Move cursor up |
| `Home` | Jump to first task |
| `End` | Jump to last task |
| `Shift + up/down` | Extend selection |
| `Alt + up` | Move task up / de-nest up |
| `Alt + down` | Move task down / de-nest down |
| `dd` | Toggle task done / undone |
| `ee` | Edit task inline |
| `ss` | Add subtask |
| `xx` | Archive task |
| `nn` | Focus quick-add input for current project |
| `Escape` | Clear selection / cancel edit or subtask input |

Double-key shortcuts (`dd`, `ee`, `ss`, `xx`, `nn`) require both keypresses within 500ms.
