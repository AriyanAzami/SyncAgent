"""The dashboard: a controller, not a viewer.

Binds to 127.0.0.1 only. Every mutating route is a POST that hands work to the
single-worker Runner, so the HTTP layer can never start two seats at once no
matter how many browser tabs are open.
"""

import http.server
import json
import re
import socketserver
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import seats as S
from . import table as T
from . import ui
from .runner import Runner
from .usage import UsageMeter, agent_state
from .util import have, now_iso, parse_ts, read_json, write_json

TURN_FILE = re.compile(r"^[0-9]{2}-[a-z0-9]+-[a-z0-9-]*\.md$")
READABLE = {"ANSWER.md", "BRIEF.md", "NEED.md"}


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------

def health_path(root):
    return T.table_dir(root) / "health.json"


def collect_state(root, runner, meter):
    cfg = T.load_config(root)
    events = T.load_telemetry(root)
    topics = T.all_topics(root)
    health = read_json(health_path(root), {})
    now = datetime.now(timezone.utc)

    seats = {}
    for name, seat in (cfg.get("seats") or {}).items():
        turns = [e for e in events if e.get("seat") == name and e.get("kind") == "turn"]
        ok_turns = [e for e in turns if e.get("ok")]
        last = ok_turns[-1]["ts"] if ok_turns else None
        seen = parse_ts(last)
        idle = round((now - seen).total_seconds()) if seen else None
        installed = have(seat.get("cmd") or name)

        # A seat's problem outlives the turn that hit it: the binary is on PATH,
        # the state looks fine, and every turn still fails. Surfacing the last
        # real error is the difference between a fixable message and a mystery.
        problem = ""
        probe = (health.get("seats") or {}).get(name) or {}
        if not installed:
            problem = f"'{seat.get('cmd') or name}' is not on your PATH."
        elif probe.get("state") == "blocked":
            problem = probe.get("detail", "")
        else:
            failed = [e for e in turns if not e.get("ok")]
            if failed and (not ok_turns or failed[-1]["ts"] > ok_turns[-1]["ts"]):
                problem = failed[-1].get("error", "")

        state = agent_state(installed, idle)
        if problem and state in ("never", "cold", "idle"):
            state = "blocked"

        seats[name] = {
            "role": seat.get("role", ""),
            "depth": seat.get("depth", T.DEFAULT_DEPTH),
            "scribe": bool(seat.get("scribe")),
            "on_call": bool(seat.get("on_call")),
            "enabled": seat.get("enabled", True),
            "installed": installed,
            "turns": len(ok_turns),
            "idle_seconds": idle,
            "state": state,
            "problem": problem,
        }

    out = []
    for topic in topics:
        d = T.topic_dir(root, topic["id"])
        answer = ""
        if (d / "ANSWER.md").exists():
            answer = (d / "ANSWER.md").read_text(encoding="utf-8", errors="replace")
        item = dict(topic)
        item["answer"] = answer
        item["dir"] = str(d)
        out.append(item)

    return {
        "root": str(root),
        "seats": seats,
        "relay": T.seat_order(cfg),
        "depths": list(T.DEPTHS),
        "lenses": [{"key": k, "label": v["label"]} for k, v in T.LENSES.items()],
        "topics": out,
        "runner": runner.state(),
        "usage": meter.report(),
        "updated": now_iso(),
    }


# --------------------------------------------------------------------------
# server
# --------------------------------------------------------------------------

def build_handler(root, runner, meter):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        # ---------------------------------------------------------- plumbing

        def _send(self, body, ctype, code=200):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj, code=200):
            self._send(json.dumps(obj), "application/json", code)

        def _body(self):
            try:
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n) or b"{}")
            except (ValueError, json.JSONDecodeError):
                return {}

        # --------------------------------------------------------------- GET

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
                return self._send(ui.PAGE, "text/html; charset=utf-8")
            if parsed.path == "/api/state":
                return self._json(collect_state(root, runner, meter))
            if parsed.path == "/api/turn":
                q = parse_qs(parsed.query)
                return self._turn(q.get("topic", [""])[0], q.get("file", [""])[0])
            self.send_error(404)

        def _turn(self, topic_id, name):
            """Read one file out of one topic folder.

            Both halves are validated against a pattern and the result is
            re-checked against the topic directory, because a path assembled
            from a query string is the classic way a local dashboard turns into
            an arbitrary-file reader.
            """
            if not T.TOPIC_RE.match(topic_id or "") or "/" in topic_id or "\\" in topic_id:
                return self._json({"error": "bad topic"}, 400)
            if not (TURN_FILE.match(name or "") or name in READABLE):
                return self._json({"error": "bad file"}, 400)
            d = T.topic_dir(root, topic_id).resolve()
            path = (d / name).resolve()
            if d != path.parent or not path.is_file():
                return self._json({"error": "not found"}, 404)
            return self._json({"text": path.read_text(encoding="utf-8", errors="replace")})

        # -------------------------------------------------------------- POST

        def do_POST(self):
            path = urlparse(self.path).path
            body = self._body()

            if path == "/api/topic":
                return self._create(body)
            if path == "/api/doctor":
                return self._doctor()

            m = re.match(r"^/api/topic/([^/]+)/(run|next|answer|stop)$", path)
            if not m:
                return self.send_error(404)
            topic_id, action = m.group(1), m.group(2)
            if not T.load_topic(root, topic_id):
                return self._json({"ok": False, "error": "no such topic"}, 404)

            if action == "run":
                ok, msg = runner.enqueue(topic_id, int(body.get("step") or 0))
            elif action == "next":
                ok, msg = runner.enqueue_next(topic_id)
            elif action == "answer":
                threading.Thread(target=runner.write_answer, args=(topic_id,),
                                 daemon=True).start()
                ok, msg = True, "writing"
            else:
                ok, msg = _stop(root, topic_id)
            return self._json({"ok": ok, "error": None if ok else msg, "message": msg})

        def _create(self, body):
            need = (body.get("need") or "").strip()
            if not need:
                return self._json({"ok": False, "error": "empty need"}, 400)
            cfg = T.load_config(root)
            steps = body.get("steps") or None
            if steps:
                known = set(cfg.get("seats") or {})
                steps = [s for s in steps if s.get("seat") in known]
                if not steps:
                    return self._json({"ok": False, "error": "no valid seats in plan"}, 400)
            topic = T.create_topic(root, need, lens=body.get("lens"),
                                   steps=steps, cfg=cfg)
            if topic["steps"]:
                runner.enqueue(topic["id"], topic["steps"][0]["n"])
            return self._json({"ok": True, "topic": topic["id"]})

        def _doctor(self):
            cfg = T.load_config(root)
            results = {}
            for name, seat in (cfg.get("seats") or {}).items():
                if not seat.get("enabled", True):
                    continue
                results[name] = S.check_seat(name, seat, root)
            write_json(health_path(root), {"checked": now_iso(), "seats": results})
            return self._json({"ok": True, "seats": results})

    return Handler


def _stop(root, topic_id):
    topic = T.load_topic(root, topic_id)
    for s in topic["steps"]:
        if s["status"] == "queued":
            s["status"] = "skipped"
            s["error"] = "skipped: stopped by you"
    topic["status"] = "stopped"
    T.save_topic(root, topic)
    return True, "stopped"


class DashServer(socketserver.ThreadingTCPServer):
    # Must be a CLASS attribute: TCPServer.__init__ binds immediately, so
    # setting this on the instance afterwards is a no-op.
    allow_reuse_address = True
    daemon_threads = True


def serve(root, port=7777, open_browser=True):
    runner = Runner(root)
    claude = (T.load_config(root).get("seats") or {}).get("claude") or {}
    meter = UsageMeter(root, cmd=claude.get("cmd") or "claude").start()
    handler = build_handler(root, runner, meter)
    while True:
        try:
            httpd = DashServer(("127.0.0.1", port), handler)
            break
        except OSError:
            port += 1
            if port > 7797:
                raise
    url = f"http://127.0.0.1:{port}"
    with httpd:
        print(f"\n  The table is at {url}")
        print(f"  Folder: {Path(root) / 'table'}")
        print("  ctrl-c to stop\n")
        if open_browser:
            try:
                import webbrowser
                threading.Timer(0.6, lambda: webbrowser.open(url)).start()
            except Exception:
                pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("stopped")
