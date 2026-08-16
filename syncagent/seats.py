"""One adapter per CLI.

Each adapter turns a prompt into a `Turn`: text, token counts, and the session
id that lets the next turn skip re-sending everything. The three CLIs disagree
about output format, about flags, and about what a session even is, so the
disagreement is quarantined here and nothing above this file knows about it.

Prompts always go over **stdin**, never argv. A brief plus prior turns will
exceed ARG_MAX eventually, and that failure looks like an unrelated crash
rather than a size problem.
"""

import json
import re
import subprocess
import time

from .util import exe, have, strip_fences

DEFAULT_TIMEOUT = 900

BLANK_TOKENS = {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0, "total": 0}


class Turn(dict):
    """Result of one seat's turn. A dict so it serialises straight into topic.json."""

    @property
    def ok(self):
        return bool(self.get("ok"))


def _turn(ok, text="", tokens=None, session=None, model="", error="", elapsed=0):
    tokens = dict(tokens or BLANK_TOKENS)
    tokens.setdefault("total", tokens.get("in", 0) + tokens.get("out", 0)
                      + tokens.get("cache_read", 0) + tokens.get("cache_write", 0))
    return Turn(ok=ok, text=text, tokens=tokens, session=session,
                model=model, error=error, duration_ms=elapsed)


def _run(cmd, prompt, cwd, timeout):
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), input=prompt, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "", f"timed out after {timeout}s"
    except OSError as e:
        return None, "", f"could not start {cmd[0]}: {e}"
    return proc, proc.stdout or "", proc.stderr or ""


# --------------------------------------------------------------------------
# auth failures
# --------------------------------------------------------------------------
#
# All three CLIs report "you are not logged in" as an ordinary run that
# produced no answer. Detecting it explicitly is the difference between a
# dashboard that says "Gemini needs an API key" and one that shows an empty
# turn and leaves the user to guess.

AUTH_PATTERNS = (
    (re.compile(r"IneligibleTierError|no longer supported for Gemini Code Assist", re.I),
     "Gemini's free CLI tier has been withdrawn for individual accounts. Set "
     "GEMINI_API_KEY (from aistudio.google.com/apikey) or GOOGLE_CLOUD_PROJECT, "
     "then retry."),
    (re.compile(r"Error authenticating|not authenticated|please (re)?login|"
                r"run [`']?(gemini|codex|claude) login", re.I),
     "That CLI is installed but not signed in. Run it once by hand and complete "
     "the login it asks for."),
    (re.compile(r"invalid[_ ]api[_ ]key|401 Unauthorized|403 Forbidden", re.I),
     "The CLI's credentials were rejected. Check its API key or re-run its login."),
    (re.compile(r"quota|rate.?limit|429|resource[_ ]exhausted", re.I),
     "That CLI is out of quota right now. Try a different seat, or wait."),
)


def diagnose(stderr, stdout=""):
    blob = f"{stderr}\n{stdout}"
    for pattern, message in AUTH_PATTERNS:
        if pattern.search(blob):
            return message
    return ""


def _fail(stderr, stdout, code, elapsed):
    hint = diagnose(stderr, stdout)
    detail = (stderr or stdout or "").strip().splitlines()
    tail = detail[-1][:300] if detail else f"exit {code}"
    return _turn(False, error=hint or tail, elapsed=elapsed)


# --------------------------------------------------------------------------
# claude
# --------------------------------------------------------------------------

def run_claude(prompt, cwd, seat, session=None, writable=False,
               timeout=DEFAULT_TIMEOUT):
    """`claude -p --output-format json`.

    `--resume <session_id>` continues the exact session, so a second Claude turn
    on the same topic re-sends nothing. That is the single biggest token saving
    in the tool and the reason session ids are threaded through at all.
    """
    cmd = [exe(seat.get("cmd") or "claude"), "-p", "--output-format", "json"]
    if seat.get("model"):
        cmd += ["--model", seat["model"]]
    if session:
        cmd += ["--resume", session]
    if writable:
        cmd += ["--permission-mode", "acceptEdits"]
    else:
        # dontAsk denies anything outside the read-only command set and any
        # explicit allow rules, so an advisory seat cannot edit even if it tries.
        cmd += ["--permission-mode", "dontAsk"]

    started = time.time()
    proc, out, err = _run(cmd, prompt, cwd, timeout)
    elapsed = int((time.time() - started) * 1000)
    if proc is None:
        return _turn(False, error=err, elapsed=elapsed)

    try:
        data = json.loads(out.strip() or "{}")
    except json.JSONDecodeError:
        if proc.returncode != 0 or not out.strip():
            return _fail(err, out, proc.returncode, elapsed)
        return _turn(True, text=out.strip(), elapsed=elapsed)

    if data.get("is_error") or data.get("subtype") not in (None, "success"):
        return _turn(False, error=diagnose(err, str(data.get("result", "")))
                     or str(data.get("result") or "claude reported an error")[:300],
                     elapsed=elapsed)

    text = (data.get("result") or "").strip()
    if not text:
        return _fail(err, out, proc.returncode, elapsed)

    return _turn(True, text=text, tokens=_claude_tokens(data),
                 session=data.get("session_id"),
                 model=_claude_model(data), elapsed=elapsed)


def _claude_model(data):
    models = data.get("modelUsage") or {}
    return next(iter(models), "") or "claude"


def _claude_tokens(data):
    """Prefer `modelUsage`, which aggregates every iteration of the run.

    The top-level `usage` block reports only the final API call, so on a
    multi-turn agentic run it undercounts the input side badly - 9 tokens
    against modelUsage's 531 on a one-word prompt.
    """
    models = data.get("modelUsage") or {}
    if models:
        agg = dict(BLANK_TOKENS)
        for stats in models.values():
            agg["in"] += int(stats.get("inputTokens") or 0)
            agg["out"] += int(stats.get("outputTokens") or 0)
            agg["cache_read"] += int(stats.get("cacheReadInputTokens") or 0)
            agg["cache_write"] += int(stats.get("cacheCreationInputTokens") or 0)
        agg["total"] = sum(agg[k] for k in ("in", "out", "cache_read", "cache_write"))
        agg["cost_usd"] = round(float(data.get("total_cost_usd") or 0), 6)
        return agg

    u = data.get("usage") or {}
    agg = {
        "in": int(u.get("input_tokens") or 0),
        "out": int(u.get("output_tokens") or 0),
        "cache_read": int(u.get("cache_read_input_tokens") or 0),
        "cache_write": int(u.get("cache_creation_input_tokens") or 0),
    }
    agg["total"] = sum(agg.values())
    agg["cost_usd"] = round(float(data.get("total_cost_usd") or 0), 6)
    return agg


# --------------------------------------------------------------------------
# gemini
# --------------------------------------------------------------------------

def run_gemini(prompt, cwd, seat, session=None, writable=False,
               timeout=DEFAULT_TIMEOUT):
    """`gemini -o json --approval-mode plan`.

    `plan` is Gemini CLI's genuine read-only mode, so an advisory seat is
    prevented from writing rather than merely asked not to.

    Session reuse is best-effort: `--session-id` starts a *new* session under a
    UUID you choose, but `--resume` only takes `latest` or an index, so there is
    no supported resume-by-id. Gemini therefore re-reads the brief each turn.
    The brief is capped precisely so that this costs little.
    """
    cmd = [exe(seat.get("cmd") or "gemini"), "-o", "json"]
    cmd += ["--approval-mode", "auto_edit" if writable else "plan"]
    if seat.get("model"):
        cmd += ["-m", seat["model"]]

    started = time.time()
    proc, out, err = _run(cmd, prompt, cwd, timeout)
    elapsed = int((time.time() - started) * 1000)
    if proc is None:
        return _turn(False, error=err, elapsed=elapsed)

    text, tokens, model = _parse_gemini(out)
    if not text.strip() or proc.returncode != 0:
        return _fail(err, out, proc.returncode, elapsed)
    return _turn(True, text=text.strip(), tokens=tokens, model=model, elapsed=elapsed)


def _parse_gemini(stdout):
    """`--output-format json` -> {response, stats:{models:{name:{tokens:{...}}}}}"""
    try:
        data = json.loads(strip_fences(stdout))
    except json.JSONDecodeError:
        return stdout, dict(BLANK_TOKENS), "gemini"
    if isinstance(data, dict) and data.get("error"):
        return "", dict(BLANK_TOKENS), "gemini"
    text = (data or {}).get("response", "") if isinstance(data, dict) else ""
    tokens, model = dict(BLANK_TOKENS), "gemini"
    models = ((data or {}).get("stats") or {}).get("models") or {}
    for model_name, stats in models.items():
        tk = stats.get("tokens") or {}
        tokens = {
            "in": int(tk.get("prompt") or 0),
            "out": int(tk.get("candidates") or tk.get("response") or 0),
            "cache_read": int(tk.get("cached") or 0),
            "cache_write": 0,
        }
        tokens["total"] = int(tk.get("total") or sum(tokens.values()))
        model = model_name
        break
    return text, tokens, model


# --------------------------------------------------------------------------
# codex
# --------------------------------------------------------------------------

def run_codex(prompt, cwd, seat, session=None, writable=False,
              timeout=DEFAULT_TIMEOUT):
    """`codex exec - --json`, resumable by thread id."""
    base = [exe(seat.get("cmd") or "codex"), "exec"]
    if session:
        base += ["resume", session, "-"]
    else:
        base += ["-"]
    cmd = base + ["--json", "--skip-git-repo-check",
                  "--sandbox", "workspace-write" if writable else "read-only"]
    if not writable:
        cmd += ["--ephemeral"]
    if seat.get("model"):
        cmd += ["--model", seat["model"]]
    if seat.get("effort"):
        cmd += ["-c", f"model_reasoning_effort={seat['effort']}"]

    started = time.time()
    proc, out, err = _run(cmd, prompt, cwd, timeout)
    elapsed = int((time.time() - started) * 1000)
    if proc is None:
        return _turn(False, error=err, elapsed=elapsed)

    text, tokens, thread = _parse_codex(out)
    if not text.strip():
        return _fail(err, out, proc.returncode, elapsed)
    return _turn(True, text=text.strip(), tokens=tokens, session=thread,
                 model=seat.get("model") or "codex", elapsed=elapsed)


def _parse_codex(stdout):
    """JSONL events. Take the agent messages and the last usage block."""
    parts, tokens, thread = [], dict(BLANK_TOKENS), None
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue

        if ev.get("type") == "thread.started" and ev.get("thread_id"):
            thread = ev["thread_id"]

        item = ev.get("item") or {}
        if item.get("type") in ("agent_message", "assistant_message"):
            t = item.get("text") or item.get("content") or ""
            if isinstance(t, str) and t.strip():
                parts.append(t)

        usage = ev.get("usage") or (ev.get("turn") or {}).get("usage")
        if isinstance(usage, dict):
            tokens = {
                "in": int(usage.get("input_tokens") or 0),
                "out": int(usage.get("output_tokens") or 0),
                "cache_read": int(usage.get("cached_input_tokens") or 0),
                "cache_write": int(usage.get("cache_write_input_tokens") or 0),
            }
            tokens["total"] = int(usage.get("total_tokens")
                                  or sum(tokens.values()))
    return "\n".join(parts).strip(), tokens, thread


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------

ADAPTERS = {"claude": run_claude, "gemini": run_gemini, "codex": run_codex}


def run_seat(name, seat, prompt, cwd, session=None, writable=False,
             timeout=DEFAULT_TIMEOUT):
    adapter = ADAPTERS.get(name)
    if adapter is None:
        return _turn(False, error=f"no adapter for seat '{name}'")
    binary = seat.get("cmd") or name
    if not have(binary):
        return _turn(False, error=f"'{binary}' is not on your PATH.")
    return adapter(prompt, cwd, seat, session=session, writable=writable,
                   timeout=timeout)


PROBE = "Reply with exactly the word: ok"


def check_seat(name, seat, cwd, timeout=120):
    """Is this seat actually usable? Costs one tiny call.

    PATH presence is not enough - Gemini's individual free tier was withdrawn,
    so the binary is there, the login looks fine, and every turn fails. Only a
    real call distinguishes 'installed' from 'works'.
    """
    binary = seat.get("cmd") or name
    if not have(binary):
        return {"seat": name, "state": "missing",
                "detail": f"'{binary}' is not on your PATH."}
    turn = run_seat(name, seat, PROBE, cwd, timeout=timeout)
    if turn.ok:
        return {"seat": name, "state": "ready", "detail": turn.get("model") or "",
                "tokens": turn["tokens"].get("total", 0)}
    return {"seat": name, "state": "blocked", "detail": turn.get("error", "")}
