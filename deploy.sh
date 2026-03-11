#!/bin/bash
# Task Manager - Deploy & Server Control
# Usage:
#   ./deploy.sh --dev --start    Start dev server  → http://dev.taskmanager.local
#   ./deploy.sh --dev --stop     Stop dev server
#   ./deploy.sh --prd            Deploy to ~/.local/taskmanager → http://taskmanager.local

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="/tmp/taskmanager-dev.pid"
CADDY_PID_FILE="/tmp/taskmanager-caddy.pid"
CADDY_CONFIG="/tmp/taskmanager.Caddyfile"
INSTALL_DIR="$HOME/.local/taskmanager"
PLIST_NAME="com.local.taskmanager.plist"
CADDY_PLIST_NAME="com.local.taskmanager-caddy.plist"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
DEV_PORT=8001
PRD_PORT=8000
DEV_HOST="dev.taskmanager.local"
PRD_HOST="taskmanager.local"

ensure_hosts_entry() {
    local host="$1"
    if ! grep -q "$host" /etc/hosts 2>/dev/null; then
        echo "Adding $host to /etc/hosts (requires sudo)..."
        echo "127.0.0.1   $host" | sudo tee -a /etc/hosts > /dev/null
    fi
}

generate_caddyfile() {
    local outfile="$1"
    cat > "$outfile" <<EOF
$PRD_HOST {
    reverse_proxy localhost:$PRD_PORT
}

$DEV_HOST {
    reverse_proxy localhost:$DEV_PORT
}
EOF
}

start_caddy() {
    generate_caddyfile "$CADDY_CONFIG"
    if [ -f "$CADDY_PID_FILE" ] && kill -0 "$(cat $CADDY_PID_FILE)" 2>/dev/null; then
        caddy reload --config "$CADDY_CONFIG" 2>/dev/null && echo "Caddy config reloaded" || true
    else
        nohup caddy run --config "$CADDY_CONFIG" > /tmp/taskmanager-caddy.log 2>&1 &
        echo $! > "$CADDY_PID_FILE"
        echo "Caddy started (PID $!)"
    fi
}

stop_caddy() {
    if [ -f "$CADDY_PID_FILE" ]; then
        PID=$(cat "$CADDY_PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID"
            rm -f "$CADDY_PID_FILE"
            echo "Caddy stopped"
        else
            rm -f "$CADDY_PID_FILE"
        fi
    fi
}

case "$1" in
    --dev)
        case "$2" in
            --start)
                cd "$SCRIPT_DIR"
                if [ -d "venv" ]; then source venv/bin/activate; fi

                if [ -f "$PID_FILE" ] && kill -0 "$(cat $PID_FILE)" 2>/dev/null; then
                    echo "Task Manager (dev) already running (PID $(cat $PID_FILE))"
                    exit 0
                fi

                ensure_hosts_entry "$DEV_HOST"
                ensure_hosts_entry "$PRD_HOST"

                TASKMANAGER_DEV=1 nohup python3 -m uvicorn app:app --host 127.0.0.1 --port $DEV_PORT > /tmp/taskmanager.log 2>/tmp/taskmanager.err &
                echo $! > "$PID_FILE"
                echo "Task Manager started in dev mode (PID $!)"
                echo "  DB:     $SCRIPT_DIR/tasks.db"
                echo "  Logs:   /tmp/taskmanager.log"
                echo "  Errors: /tmp/taskmanager.err"

                start_caddy

                echo ""
                echo "  URL: http://$DEV_HOST"
                ;;
            --stop)
                if [ -f "$PID_FILE" ]; then
                    PID=$(cat "$PID_FILE")
                    if kill -0 "$PID" 2>/dev/null; then
                        kill "$PID"
                        rm -f "$PID_FILE"
                        echo "Task Manager (dev) stopped (PID $PID)"
                    else
                        rm -f "$PID_FILE"
                        echo "Task Manager not running (stale PID file removed)"
                    fi
                else
                    echo "Task Manager not running (no PID file found)"
                fi
                stop_caddy
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
            if launchctl list | grep -q "com.local.taskmanager$"; then
                echo "Stopping app service..."
                launchctl unload "$LAUNCH_AGENTS/$PLIST_NAME" 2>/dev/null || true
            fi
            if launchctl list | grep -q "com.local.taskmanager-caddy"; then
                echo "Stopping caddy service..."
                launchctl unload "$LAUNCH_AGENTS/$CADDY_PLIST_NAME" 2>/dev/null || true
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

        # Generate app plist (uses $HOME so no hardcoded username)
        echo "Installing app Launch Agent..."
        mkdir -p "$LAUNCH_AGENTS"
        cat > "$LAUNCH_AGENTS/$PLIST_NAME" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.local.taskmanager</string>
    <key>ProgramArguments</key>
    <array>
        <string>$INSTALL_DIR/venv/bin/python</string>
        <string>$INSTALL_DIR/app.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/taskmanager.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/taskmanager.err</string>
</dict>
</plist>
EOF

        # Generate Caddyfile
        PRD_CADDYFILE="$INSTALL_DIR/Caddyfile"
        generate_caddyfile "$PRD_CADDYFILE"

        # Generate Caddy plist
        echo "Installing Caddy Launch Agent..."
        CADDY_BIN="$(which caddy)"
        cat > "$LAUNCH_AGENTS/$CADDY_PLIST_NAME" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.local.taskmanager-caddy</string>
    <key>ProgramArguments</key>
    <array>
        <string>$CADDY_BIN</string>
        <string>run</string>
        <string>--config</string>
        <string>$PRD_CADDYFILE</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/taskmanager-caddy.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/taskmanager-caddy.err</string>
</dict>
</plist>
EOF

        ensure_hosts_entry "$PRD_HOST"
        ensure_hosts_entry "$DEV_HOST"

        echo "Starting services..."
        launchctl load "$LAUNCH_AGENTS/$PLIST_NAME"
        launchctl load "$LAUNCH_AGENTS/$CADDY_PLIST_NAME"

        sleep 2
        if curl -s "http://$PRD_HOST" > /dev/null 2>&1; then
            echo ""
            echo "=== Deploy successful ==="
            echo "  URL: http://$PRD_HOST"
        else
            echo ""
            echo "=== Deploy complete ==="
            echo "Check logs if app is not responding:"
            echo "  cat /tmp/taskmanager.log"
            echo "  cat /tmp/taskmanager.err"
            echo "  cat /tmp/taskmanager-caddy.log"
        fi
        ;;
    *)
        echo "Usage: $0 [--dev --start|--dev --stop|--prd]"
        exit 1
        ;;
esac
