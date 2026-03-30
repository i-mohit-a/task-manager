# Task Manager

A keyboard-driven local task manager. Stores tasks in a plain text file. Runs as a local web app and as a VS Code extension.

---

## Requirements

- macOS
- Python 3.8+
- `uvicorn` and `starlette` (see `requirements.txt`)

```bash
pip install -r requirements.txt
```

---

## Project Structure

```
task-manager/
├── app.py                    # Starlette web app, routes, AJAX handlers
├── storage.py                # Plain text file storage layer
├── task_parser.py            # Parses inline task input syntax
├── requirements.txt          # Python dependencies
├── templates/
│   ├── base.html             # Layout, CSS, settings UI
│   ├── index.html            # Main task view and keyboard navigation
│   ├── projects.html         # Project management
│   ├── flags.html            # Flag listing and deletion
│   └── archive.html          # Archived tasks and projects
├── tests/
│   ├── test_unit.py
│   └── test_integration.py
└── task-manager-vscode-v2/   # VS Code extension (wraps the Python app)
```

---

## Running

```bash
TASKMANAGER_DEV=1 python3 -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

Open: http://127.0.0.1:8000

`TASKMANAGER_DEV=1` makes the app read/write `tasks.txt` and `tasks.archive.txt` in the project directory. Without it, the app uses `~/Library/Application Support/TaskManager/tasks.txt`.

---

## VS Code Extension

The extension starts the Python server automatically and opens the app inside a VS Code panel.

**Install:**

1. VS Code → Extensions panel → `···` menu → `Install from VSIX`
2. Pick `task-manager-vscode-v2/task-manager-v2-0.1.0.vsix`

**Use:**

Open the command palette (`⌘⇧P`) → `Task Manager: Open`

The extension starts `uvicorn` on port 17823. The panel is a full VS Code webview — copy/paste and all keyboard shortcuts work normally.

---

## Storage

Tasks are stored in plain text files:

| Mode        | File                                                                        |
|-------------|-----------------------------------------------------------------------------|
| Dev         | `tasks.txt` and `tasks.archive.txt` in the project directory               |
| Production  | `~/Library/Application Support/TaskManager/tasks.txt` (and `.archive.txt`) |

The format is human-readable and can be edited directly. The server reloads automatically when the file changes on disk.

---

## Pages

| Page     | Path        |
|----------|-------------|
| Tasks    | `/`         |
| Projects | `/projects` |
| Flags    | `/flags`    |
| Archive  | `/archive`  |

---

## Features

### Projects

Tasks are organised into projects. Each project has its own task list on the home page.

- Create projects from the Projects page
- Rename a project with `ee` or clicking `[e]`
- Archive a project — also archives all its tasks
- Archived projects and tasks can be restored from the Archive page
- Reorder projects with `alt+↑` / `alt+↓`; order persists

---

### Tasks

Each task can have:

- a title
- a priority: `critical`, `major`, or `minor` (default: `minor`)
- an effort estimate in hours (e.g. `~4h`)
- a start date and a due date
- one or more flags (tags)
- subtasks (up to 3 levels deep)

Incomplete tasks always appear above completed tasks within their list.

---

### Task Input Syntax

All task fields can be set in a single text input when adding or editing:

```
task title [flag1] [flag2] !priority ~Nh >YYYY-MM-DD <YYYY-MM-DD
```

| Part       | Syntax     | Example         | Notes                                  |
|------------|------------|-----------------|----------------------------------------|
| Title      | plain text | `Fix signup bug`| anything not matched by other tokens  |
| Flag       | `[name]`   | `[auth]`        | any word in brackets; multiple allowed |
| Priority   | `!level`   | `!critical`     | `critical`, `major`, or `minor`        |
| Effort     | `~Nh`      | `~4h`           | hours prefixed with `~`               |
| Start date | `>date`    | `>2026-03-10`   | YYYY-MM-DD                             |
| Due date   | `<date`    | `<2026-03-31`   | YYYY-MM-DD                             |

Token order does not matter. Example:

```
Fix signup bug [auth] [backend] !critical ~2h >2026-03-10 <2026-03-15
```

---

### Subtasks

Tasks can have subtasks up to 3 levels deep (level 0 is root).

- Press `ss` on any task to add a subtask inline
- Completing a parent also completes all incomplete subtasks (same timestamp)
- Undoing a parent reverts only subtasks completed at that same timestamp
- A subtask cannot be marked undone if its parent is still completed
- Archiving or restoring a task cascades to all its subtasks

---

### Completing Tasks

Toggle done/undone with `dd` or clicking `[done]` / `[undo]`. When marked done the task moves below the new-task input line and shows the completion date.

---

### Editing Tasks

Press `ee` or click `[edit]` to edit inline. All current values are pre-filled using the same input syntax. Press Enter to save, Escape to cancel. Flags not present in the edited input are removed automatically.

---

### Flags

Free-form tags applied to tasks. Each flag name gets a consistent colour (8 options) shown as a badge.

- Add flags with `[flagname]` in the task input
- Remove a flag by editing the task and omitting it
- View all flags at `/flags`; deleting a flag there removes it from all tasks

---

### Archiving

Press `xx` or click `[x]` to archive a task and all its subtasks. Archived tasks appear at `/archive` and can be restored.

---

### Sorting

Each project header has sort controls:

- `[sort:priority]` — critical first, completed tasks last
- `[sort:effort]` — highest effort first, completed tasks last
- `[sort:tag]` — prompts for a flag name, floats matching tasks to the top

Sorting is client-side only and resets on page reload.

---

### Moving Tasks

Press `alt+↑` / `alt+↓` to reorder tasks. Positions persist.

- Moving within the same level swaps with the adjacent sibling
- Moving across levels nests or de-nests the task one level per keypress
- Tasks carry their subtrees when moved
- Tasks cannot be moved across projects

---

### Multi-Select

Hold `shift+↑` / `shift+↓` to extend the selection. `alt+↑` / `alt+↓` moves all selected tasks together. Press Escape to clear.

---

### Quick Add

Each project has a quick-add input positioned just above any completed tasks. Press `nn` to focus it. Type using the inline syntax and press Enter to add. Press Escape to clear and dismiss.

---

### Settings

A settings panel (gear icon, top-right) with three toggles, all persisted in `localStorage`:

| Toggle     | Effect                                    |
|------------|-------------------------------------------|
| Font size  | Compact mode — smaller font throughout    |
| Task lines | Show a separator line under each task row |
| Dense      | Tighter line spacing                      |

---

### Keyboard Shortcuts

Double-key shortcuts (`dd`, `ee`, `ss`, `xx`, `nn`) require both keypresses within 500ms. All shortcuts work when no input is focused.

**Home page (`/`)**

| Key            | Action                                                        |
|----------------|---------------------------------------------------------------|
| `↑` / `↓`      | Move cursor linearly through all rows and quick-add inputs    |
| `Home`         | Jump to first task                                            |
| `End`          | Jump to last task                                             |
| `shift+↑/↓`    | Extend selection                                              |
| `alt+↑/↓`      | Move task up or down (persisted)                              |
| `dd`           | Toggle task done / undone                                     |
| `ee`           | Edit task inline                                              |
| `ss`           | Add subtask                                                   |
| `xx`           | Archive task                                                  |
| `nn`           | Focus quick-add for current project                           |
| `Escape`       | Clear selection, cancel edit or subtask                       |

**Projects page (`/projects`)**

| Key            | Action                                  |
|----------------|-----------------------------------------|
| `↑` / `↓`      | Move cursor                             |
| `shift+↑/↓`    | Extend selection                        |
| `alt+↑/↓`      | Reorder selected projects (persisted)   |
| `ee`           | Rename project at cursor                |
| `nn`           | Focus new project input                 |
| `xx`           | Archive project at cursor               |
