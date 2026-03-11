#!/bin/bash
# Task Manager - Deploy & Server Control
# Usage:
#   ./deploy.sh --dev --start    Start server locally in background (TASKMANAGER_DEV=1)
#   ./deploy.sh --dev --stop     Stop local dev server
#   ./deploy.sh --prd            Deploy to ~/.local/taskmanager and start via launchd

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="/tmp/taskmanager.pid"
INSTALL_DIR="$HOME/.local/taskmanager"
PLIST_NAME="com.local.taskmanager.plist"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

case "$1" in
    --dev)
        case "$2" in
            --start)
                cd "$SCRIPT_DIR"
                if [ -d "venv" ]; then source venv/bin/activate; fi

                if [ -f "$PID_FILE" ] && kill -0 "$(cat $PID_FILE)" 2>/dev/null; then
                    echo "Task Manager already running (PID $(cat $PID_FILE))"
                    exit 0
                fi

                TASKMANAGER_DEV=1 nohup python app.py > /tmp/taskmanager.log 2>/tmp/taskmanager.err &
                echo $! > "$PID_FILE"
                echo "Task Manager started in dev mode (PID $!)"
                echo "  URL:    http://127.0.0.1:8000"
                echo "  DB:     $SCRIPT_DIR/tasks.db"
                echo "  Logs:   /tmp/taskmanager.log"
                echo "  Errors: /tmp/taskmanager.err"
                ;;
            --stop)
                if [ -f "$PID_FILE" ]; then
                    PID=$(cat "$PID_FILE")
                    if kill -0 "$PID" 2>/dev/null; then
                        kill "$PID"
                        rm -f "$PID_FILE"
                        echo "Task Manager stopped (PID $PID)"
                    else
                        rm -f "$PID_FILE"
                        echo "Task Manager not running (stale PID file removed)"
                    fi
                else
                    echo "Task Manager not running (no PID file found)"
                fi
                ;;
            *)
                echo "Usage: $0 --dev [--start|--stop]"
                exit 1
                ;;
        esac
        ;;
    --prd)
        set -e
        echo "=== Task Manager Deploy ==="
        echo "Source: $SCRIPT_DIR"
        echo "Target: $INSTALL_DIR"
        echo ""

        if [ -d "$INSTALL_DIR" ]; then
            echo "Updating existing installation..."
            if launchctl list | grep -q "com.local.taskmanager"; then
                echo "Stopping service..."
                launchctl unload "$LAUNCH_AGENTS/$PLIST_NAME" 2>/dev/null || true
            fi
            BACKUP_DIR="$INSTALL_DIR/backup_$(date +%Y%m%d_%H%M%S)"
            echo "Creating backup at $BACKUP_DIR..."
            mkdir -p "$BACKUP_DIR"
            cp -f "$INSTALL_DIR/app.py" "$BACKUP_DIR/" 2>/dev/null || true
            cp -rf "$INSTALL_DIR/templates" "$BACKUP_DIR/" 2>/dev/null || true
        else
            echo "Fresh installation..."
            mkdir -p "$INSTALL_DIR"
        fi

        echo "Copying files..."
        cp "$SCRIPT_DIR/app.py" "$INSTALL_DIR/"
        cp "$SCRIPT_DIR/database.py" "$INSTALL_DIR/"
        cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"
        cp -r "$SCRIPT_DIR/templates" "$INSTALL_DIR/"

        if [ ! -d "$INSTALL_DIR/venv" ]; then
            echo "Creating virtual environment..."
            python3 -m venv "$INSTALL_DIR/venv"
            echo "Installing dependencies..."
            "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
        fi

        if [ ! -f "$LAUNCH_AGENTS/$PLIST_NAME" ]; then
            echo "Installing Launch Agent..."
            mkdir -p "$LAUNCH_AGENTS"
            cp "$SCRIPT_DIR/$PLIST_NAME" "$LAUNCH_AGENTS/"
        fi

        echo "Starting service..."
        launchctl load "$LAUNCH_AGENTS/$PLIST_NAME"

        sleep 2
        if curl -s "http://127.0.0.1:8000" > /dev/null 2>&1; then
            echo ""
            echo "=== Deploy successful ==="
            echo "App running at http://127.0.0.1:8000"
            echo "DB: ~/Library/Application Support/TaskManager/tasks.db"
        else
            echo ""
            echo "=== Deploy complete ==="
            echo "Check logs if app is not responding:"
            echo "  cat /tmp/taskmanager.log"
            echo "  cat /tmp/taskmanager.err"
        fi
        ;;
    *)
        echo "Usage: $0 [--dev --start|--dev --stop|--prd]"
        exit 1
        ;;
esac
