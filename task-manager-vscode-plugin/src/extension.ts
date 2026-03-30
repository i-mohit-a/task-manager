import * as vscode from 'vscode';
import { spawn, ChildProcess } from 'child_process';
import * as path from 'path';
import * as http from 'http';

const PORT = 17823;

let server: ChildProcess | undefined;
let panel: vscode.WebviewPanel | undefined;

// The app lives one directory above this extension
function getAppDir(extensionUri: vscode.Uri): string {
    return path.join(extensionUri.fsPath, '..');
}

function waitForServer(retries = 25): Promise<void> {
    return new Promise((resolve, reject) => {
        let n = 0;
        const try_ = () => {
            const req = http.get(`http://127.0.0.1:${PORT}/`, res => {
                res.resume();
                resolve();
            });
            req.on('error', () => {
                if (++n >= retries) { reject(new Error('server did not start in time')); }
                else { setTimeout(try_, 400); }
            });
            req.end();
        };
        try_();
    });
}

async function ensureServer(appDir: string): Promise<void> {
    if (server) { return; }
    server = spawn('python3', [
        '-m', 'uvicorn', 'app:app',
        '--host', '127.0.0.1',
        '--port', String(PORT),
        '--log-level', 'warning'
    ], {
        cwd: appDir,
        env: { ...process.env, TASKMANAGER_DEV: '1' },
    });
    server.on('error', err => {
        vscode.window.showErrorMessage(`Task Manager: ${err.message}`);
    });
    await waitForServer();
}

function fetchPage(urlPath: string): Promise<string> {
    return new Promise((resolve, reject) => {
        http.get(`http://127.0.0.1:${PORT}${urlPath}`, res => {
            let data = '';
            res.on('data', (chunk: Buffer) => { data += chunk; });
            res.on('end', () => { resolve(data); });
        }).on('error', reject);
    });
}

function transformHtml(html: string): string {
    // CSP: allow inline scripts/styles, and fetch to localhost
    const csp = `<meta http-equiv="Content-Security-Policy" content="`
        + `default-src 'none'; `
        + `script-src 'unsafe-inline'; `
        + `style-src 'unsafe-inline'; `
        + `connect-src http://127.0.0.1:${PORT}; `
        + `img-src data: http://127.0.0.1:${PORT};">`;

    // Injected into every page:
    // 1. Intercept <a href="/..."> clicks → send postMessage to extension
    // 2. Patch window.fetch so relative URLs resolve to localhost, not vscode-webview://
    const injected = `<script>
(function() {
    const vscode = acquireVsCodeApi();

    document.addEventListener('click', function(e) {
        const a = e.target.closest('a[href]');
        if (!a) { return; }
        const href = a.getAttribute('href');
        if (href && href.startsWith('/')) {
            e.preventDefault();
            vscode.postMessage({ type: 'navigate', path: href });
        }
    }, true);

    const _fetch = window.fetch;
    window.fetch = function(url, opts) {
        if (typeof url === 'string' && url.startsWith('/')) {
            url = 'http://127.0.0.1:${PORT}' + url;
        }
        return _fetch.call(this, url, opts);
    };
})();
</script>`;

    return html
        .replace('<head>', `<head>${csp}`)
        .replace('</body>', `${injected}</body>`);
}

async function loadPage(urlPath: string): Promise<void> {
    if (!panel) { return; }
    try {
        const html = await fetchPage(urlPath);
        panel.webview.html = transformHtml(html);
    } catch (err) {
        panel.webview.html = `<body style="font-family:monospace;padding:20px;color:#c00">
            Failed to load ${urlPath}: ${err}
        </body>`;
    }
}

export function activate(context: vscode.ExtensionContext): void {
    const appDir = getAppDir(context.extensionUri);

    context.subscriptions.push(
        vscode.commands.registerCommand('taskManager.open', async () => {
            if (panel) {
                panel.reveal();
                return;
            }

            try {
                await ensureServer(appDir);
            } catch (err) {
                vscode.window.showErrorMessage(`Task Manager: could not start server — ${err}`);
                return;
            }

            panel = vscode.window.createWebviewPanel(
                'taskManager',
                'Task Manager',
                vscode.ViewColumn.One,
                { enableScripts: true, retainContextWhenHidden: true }
            );

            panel.webview.onDidReceiveMessage(async (msg: { type: string; path: string }) => {
                if (msg.type === 'navigate') {
                    await loadPage(msg.path);
                }
            });

            panel.onDidDispose(() => { panel = undefined; });

            await loadPage('/');
        })
    );
}

export function deactivate(): void {
    server?.kill();
    server = undefined;
}
