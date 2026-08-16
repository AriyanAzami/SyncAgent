"""The relay.

One queue, one worker thread, one CLI alive at a time. That is not a tuning
choice - it is the token guarantee. Three agents answering the same question
simultaneously is the failure mode this tool exists to avoid, so the design
makes it impossible rather than discouraged.

The plan runs in order. A seat's handoff can insert one extra step. `none` ends
the topic. That is the whole control flow.
"""

import queue
import threading
import traceback

from . import prompts as P
from . import seats as S
from . import table as T
from .util import now_iso

LOCK = threading.RLock()


class Runner:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.running = None          # {"topic":..., "seat":..., "since":...}
        self.last_error = None
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()

    # ---------------------------------------------------------------- public

    def enqueue(self, topic_id, step_n, reason="queued"):
        with LOCK:
            topic = T.load_topic(self.root, topic_id)
            if not topic:
                return False, f"no topic '{topic_id}'"
            step = _step(topic, step_n)
            if not step:
                return False, f"topic {topic_id} has no step {step_n}"
            if step["status"] == "running":
                return False, f"step {step_n} is already running"
            step["status"] = "queued"
            step["error"] = None
            T.save_topic(self.root, topic)
        self.q.put((topic_id, step_n, reason))
        return True, "queued"

    def enqueue_next(self, topic_id):
        """Queue the first step that has not run yet."""
        with LOCK:
            topic = T.load_topic(self.root, topic_id)
            if not topic:
                return False, f"no topic '{topic_id}'"
            pending = [s for s in topic["steps"] if s["status"] in ("queued", "skipped")]
        if not pending:
            return False, "nothing left to run"
        return self.enqueue(topic_id, pending[0]["n"])

    def state(self):
        with LOCK:
            return {
                "running": dict(self.running) if self.running else None,
                "waiting": self.q.qsize(),
                "last_error": self.last_error,
            }

    # ---------------------------------------------------------------- worker

    def _loop(self):
        while True:
            topic_id, step_n, reason = self.q.get()
            try:
                self._run_one(topic_id, step_n, reason)
            except Exception:
                self.last_error = traceback.format_exc(limit=4)
                T.log_event(self.root, {"kind": "crash", "topic": topic_id,
                                        "step": step_n, "error": self.last_error})
            finally:
                with LOCK:
                    self.running = None
                self.q.task_done()

    def _run_one(self, topic_id, step_n, reason):
        with LOCK:
            topic = T.load_topic(self.root, topic_id)
            if not topic:
                return
            step = _step(topic, step_n)
            if not step or step["status"] == "done":
                return
            cfg = T.load_config(self.root)
            seat_name = step["seat"]
            seat = (cfg.get("seats") or {}).get(seat_name)
            if not seat or not seat.get("enabled", True):
                step["status"] = "failed"
                step["error"] = f"seat '{seat_name}' is not configured or is disabled"
                T.save_topic(self.root, topic)
                return
            step["status"] = "running"
            step["started"] = now_iso()
            T.save_topic(self.root, topic)
            self.running = {"topic": topic_id, "seat": seat_name,
                            "step": step_n, "since": step["started"]}
            prompt = self._build_prompt(topic, step, cfg)
            session = (topic.get("sessions") or {}).get(seat_name)
            writable = bool(seat.get("scribe"))

        # Outside the lock: this is the slow part, and the dashboard must stay
        # responsive while a seat thinks.
        turn = S.run_seat(seat_name, seat, prompt, self.root,
                          session=session, writable=writable,
                          timeout=int(cfg.get("timeout_seconds") or S.DEFAULT_TIMEOUT))

        with LOCK:
            topic = T.load_topic(self.root, topic_id)
            step = _step(topic, step_n)
            step["finished"] = now_iso()
            step["tokens"] = turn["tokens"]
            step["duration_ms"] = turn["duration_ms"]
            step["model"] = turn.get("model", "")

            if not turn.ok:
                step["status"] = "failed"
                step["error"] = turn.get("error") or "the seat returned nothing"
                T.save_topic(self.root, topic)
                T.log_event(self.root, {"kind": "turn", "topic": topic_id,
                                        "seat": seat_name, "step": step_n,
                                        "ok": False, "error": step["error"],
                                        "duration_ms": turn["duration_ms"]})
                return

            # The file lands before anything else is decided. A turn that
            # produced work must leave that work on disk even if the handoff
            # is malformed or the process dies in the next second.
            path = self._write_turn(topic, step, turn)
            step["file"] = path.name
            step["status"] = "done"
            if turn.get("session"):
                topic.setdefault("sessions", {})[seat_name] = turn["session"]

            known = set((cfg.get("seats") or {}).keys())
            step["handoff"] = T.parse_handoff(turn["text"], known_seats=known)
            T.save_topic(self.root, topic)
            T.log_event(self.root, {"kind": "turn", "topic": topic_id,
                                    "seat": seat_name, "step": step_n, "ok": True,
                                    "model": turn.get("model", ""),
                                    "depth": step.get("depth"),
                                    "tokens_total": turn["tokens"].get("total", 0),
                                    "duration_ms": turn["duration_ms"],
                                    "output": path.name})

        self._advance(topic_id, step_n, cfg)

    # ------------------------------------------------------------- decisions

    def _advance(self, topic_id, step_n, cfg):
        """What happens after a turn: stop, detour, or continue the plan."""
        if not cfg.get("auto_relay", True):
            return

        with LOCK:
            topic = T.load_topic(self.root, topic_id)
            step = _step(topic, step_n)
            handoff = step.get("handoff") or {}
            to = handoff.get("to")

            if to == "none":
                topic["status"] = "answered"
                for s in topic["steps"]:
                    if s["status"] == "queued":
                        s["status"] = "skipped"
                        s["error"] = f"skipped: {step['seat']} closed the topic"
                T.save_topic(self.root, topic)
                self._maybe_answer(topic_id, cfg)
                return

            if to == "user":
                topic["status"] = "waiting"
                T.save_topic(self.root, topic)
                return

            # Order is list position, not `n`. `n` is a stable id that ends up
            # in the turn filename, so an inserted detour keeps a fresh id while
            # sitting immediately after the step that asked for it - looking for
            # the next step by id would skip straight past the rest of the plan.
            steps = topic["steps"]
            idx = next((i for i, s in enumerate(steps) if s["n"] == step_n), len(steps))
            next_planned = next((s for s in steps[idx + 1:]
                                 if s["status"] == "queued"), None)

            # A handoff naming someone other than the next planned seat is a
            # detour: insert it, run it, then rejoin the plan. Capped by hops
            # so a pair of seats cannot volley forever.
            detour = (handoff.get("dispatchable")
                      and to
                      and (next_planned is None or next_planned["seat"] != to)
                      and topic.get("hops", 0) < int(cfg.get("max_hops", 3)))
            if detour:
                inserted = self._insert_step(topic, step_n, to, handoff)
                topic["hops"] = topic.get("hops", 0) + 1
                T.save_topic(self.root, topic)
                target = inserted["n"]
            elif next_planned:
                target = next_planned["n"]
            else:
                topic["status"] = "answered"
                T.save_topic(self.root, topic)
                self._maybe_answer(topic_id, cfg)
                return

        self.enqueue(topic_id, target, reason="relay")

    def _insert_step(self, topic, after_n, seat_name, handoff):
        cfg_seat = (T.load_config(self.root).get("seats") or {}).get(seat_name, {})
        new = {
            "n": max(s["n"] for s in topic["steps"]) + 1,
            "seat": seat_name,
            "job": handoff.get("job") or cfg_seat.get("role") or "take a look",
            "depth": cfg_seat.get("depth", T.DEFAULT_DEPTH),
            "status": "queued",
            "file": None,
            "started": None,
            "finished": None,
            "tokens": {},
            "handoff": None,
            "error": None,
            "why": handoff.get("why", ""),
            "inserted_after": after_n,
        }
        steps = topic["steps"]
        idx = next((i for i, s in enumerate(steps) if s["n"] == after_n), len(steps) - 1)
        steps.insert(idx + 1, new)
        return new

    def _maybe_answer(self, topic_id, cfg):
        """Synthesise ANSWER.md once the chain has ended.

        Only worth a call when more than one seat actually spoke - with a single
        turn, ANSWER.md would just be that turn again at full price.
        """
        if not cfg.get("auto_answer", True):
            return
        with LOCK:
            topic = T.load_topic(self.root, topic_id)
            done = [s for s in topic["steps"] if s["status"] == "done"]
            if len(done) < 2:
                return
            if (T.topic_dir(self.root, topic_id) / "ANSWER.md").exists():
                return
        self.write_answer(topic_id)

    # ---------------------------------------------------------------- answer

    def write_answer(self, topic_id):
        """The scribe reads the turns and writes the thing the human reads."""
        with LOCK:
            cfg = T.load_config(self.root)
            topic = T.load_topic(self.root, topic_id)
            if not topic:
                return False, "no such topic"
            name = T.scribe(cfg)
            if not name:
                return False, "no scribe seat is enabled"
            seat = cfg["seats"][name]
            brief = _read(T.topic_dir(self.root, topic_id) / "BRIEF.md")
            prior = T.prior_turns(self.root, topic,
                                  upto_n=10 ** 6, depth="deep")
            prompt = P.ANSWER_TEMPLATE.format(
                SEAT=name,
                BRIEF=brief,
                PRIOR=("## What the seats said\n\n" + prior) if prior else "",
            )
            session = (topic.get("sessions") or {}).get(name)
            self.running = {"topic": topic_id, "seat": name,
                            "step": "answer", "since": now_iso()}

        turn = S.run_seat(name, seat, prompt, self.root, session=session,
                          writable=bool(seat.get("scribe")))

        with LOCK:
            self.running = None
            topic = T.load_topic(self.root, topic_id)
            if not turn.ok:
                topic["answer_error"] = turn.get("error", "")
                T.save_topic(self.root, topic)
                return False, turn.get("error", "the scribe returned nothing")
            (T.topic_dir(self.root, topic_id) / "ANSWER.md").write_text(
                turn["text"].strip() + "\n", encoding="utf-8")
            topic["answer_error"] = None
            topic["answered_at"] = now_iso()
            if turn.get("session"):
                topic.setdefault("sessions", {})[name] = turn["session"]
            T.save_topic(self.root, topic)
            T.log_event(self.root, {"kind": "answer", "topic": topic_id, "seat": name,
                                    "tokens_total": turn["tokens"].get("total", 0),
                                    "duration_ms": turn["duration_ms"]})
        return True, "ANSWER.md written"

    # ---------------------------------------------------------------- prompt

    def _build_prompt(self, topic, step, cfg):
        d = T.topic_dir(self.root, topic["id"])
        depth = T.DEPTHS.get(step.get("depth"), T.DEPTHS[T.DEFAULT_DEPTH])
        seat_name = step["seat"]
        seat = cfg["seats"][seat_name]

        # A seat that keeps its own session has already been told all of this.
        # Re-sending it would defeat the point of resuming at all.
        resumed = bool((topic.get("sessions") or {}).get(seat_name))
        brief = "" if resumed else _read(d / "BRIEF.md")
        if resumed:
            brief = ("(You already have this table's brief from your previous turn "
                     "on this topic. Do not ask for it again.)")

        prior = T.prior_turns(self.root, topic, step["n"], step.get("depth"))
        others = [n for n in (cfg.get("seats") or {})
                  if n != seat_name and cfg["seats"][n].get("enabled", True)]

        # "Someone has already done the deep pass" is false when this seat is
        # first - which happens whenever a deeper seat is blocked or the plan
        # was reordered by hand. Telling a seat to react to work that does not
        # exist makes it either invent the work or argue with the instruction.
        rule = depth["rule"] if prior else depth.get("rule_first", depth["rule"])

        template = _read(T.table_dir(self.root) / "prompts" / "turn.md") \
            or P.TURN_TEMPLATE
        return template.format(
            SEAT=seat_name,
            ROLE=seat.get("role", "help"),
            JOB=step.get("job", "take a look"),
            DEPTH=depth["label"],
            DEPTH_RULE=rule,
            WORDS=depth["words"],
            BRIEF=brief,
            PRIOR=("## What earlier seats concluded\n\n" + prior) if prior
                  else "You are first. Nobody has looked at this yet.",
            SEATS=" | ".join(others) or "none",
            SCRIBE_NOTE=P.SCRIBE_NOTE if seat.get("scribe") else P.READONLY_NOTE,
        )

    def _write_turn(self, topic, step, turn):
        d = T.topic_dir(self.root, topic["id"])
        path = d / T.turn_filename(step)
        header = (f"<!-- {step['seat']} / {step.get('depth')} / {now_iso()} / "
                  f"{turn['tokens'].get('total', 0)} tokens -->\n\n")
        path.write_text(header + turn["text"].strip() + "\n", encoding="utf-8")
        return path


def _step(topic, n):
    for s in (topic or {}).get("steps", []):
        if s.get("n") == n:
            return s
    return None


def _read(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
