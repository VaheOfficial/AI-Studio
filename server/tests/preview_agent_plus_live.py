"""Read-only localhost view of an isolated Agent+ verification run."""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HTML = r'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Agent+ live test</title>
<style>body{background:#101216;color:#e7eaf0;font:16px system-ui;max-width:1100px;margin:36px auto;padding:0 24px}h1{margin-bottom:8px}small,p{color:#adb6c5}section{background:#1a1e26;border:1px solid #303846;border-radius:12px;padding:20px;margin:20px 0}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:10px;border-bottom:1px solid #303846}a{color:#8bc9ff}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px ui-monospace}summary{cursor:pointer;padding:7px}#state{font-size:24px;color:#8bc9ff}.tag{display:inline-block;margin-right:25px}li{margin:8px 0}</style>
<h1>Agent+ live test</h1><p>Read-only view of the supervised local Qwen run. Synthetic media metadata; refreshes every 4 seconds.</p><section><div id="state">Loading…</div><p id="counts"></p><details><summary>Mission objective</summary><pre id="objective"></pre></details></section>
<section><h2>Work</h2><div id="work"></div></section><section><h2>Tools and validation</h2><table><thead><tr><th>Tool</th><th>Revision</th><th>Status</th></tr></thead><tbody id="tools"></tbody></table></section>
<section><h2>Recent events</h2><div id="events"></div></section><section><h2>Run records</h2><ul><li><a href="/status.json">Current status JSON</a></li><li><a href="/run.json">Full run snapshot JSON</a></li><li><a href="/verification.json">Independent verification JSON</a></li><li><a href="/final.json">Final result JSON (available after the run ends)</a></li></ul></section>
<script>const el=id=>document.getElementById(id);const text=(tag,value)=>{const e=document.createElement(tag);e.textContent=value;return e};async function update(){try{const s=await fetch('/status.json',{cache:'no-store'}).then(r=>r.json());el('state').textContent=s.mission.status;el('counts').textContent=`Elapsed ${Math.floor(s.elapsed_seconds/60)}m ${s.elapsed_seconds%60}s · Release ${s.release} · ${new Date().toLocaleTimeString()}`;el('objective').textContent=s.mission.objective;el('work').replaceChildren(...s.work.map(w=>text('p',`${w.status}: ${w.description||w.label||w.name||w.id||JSON.stringify(w)}`)));el('tools').replaceChildren(...s.tools.map(t=>{const tr=document.createElement('tr');[t.name,t.revision,t.status].forEach(v=>tr.append(text('td',v)));return tr}));el('events').replaceChildren(...s.last_events.slice().reverse().map(e=>{const d=document.createElement('details');d.append(text('summary',`${e.created_at} · ${e.kind}: ${e.text}`),text('pre',JSON.stringify(e.data,null,2)));return d}));}catch(e){el('state').textContent='Waiting for readable run snapshot';}}update();setInterval(update,4000);</script></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8878)
    args = parser.parse_args()
    root = args.run.resolve(strict=True)
    allowed = {'status.json', 'run.json', 'verification.json', 'final.json'}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            route = self.path.partition('?')[0]
            if route == '/':
                body, mime = HTML.encode('utf-8'), 'text/html; charset=utf-8'
            elif route.lstrip('/') in allowed and route.count('/') == 1:
                try:
                    body = (root / route[1:]).read_bytes()
                except FileNotFoundError:
                    self.send_error(404, 'This record is not available yet')
                    return
                mime = 'application/json; charset=utf-8'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(json.dumps({'url': f'http://127.0.0.1:{args.port}', 'run': str(root)}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
