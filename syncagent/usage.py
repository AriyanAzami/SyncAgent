"""What Claude has left, asked of Claude.

`/usage` is a local slash command. `claude -p /usage` answers it off the same
meter the app itself draws, without making an API call: zero tokens, zero cost,
about a quarter of a second. It reports the real percentages Anthropic is
metering you on.

Earlier versions of SyncAgent estimated the same numbers by weighting the token
counts in ~/.claude/projects/*.jsonl against guessed subscription ceilings.
Anthropic does not publish those ceilings, so the guesses were the weakest thing
on the dashboard - a gauge that reads 23% when you are actually at 60% is worse
than no gauge. Asking beats estimating, so now we ask.

tests/test_usage.py is the regression guard for the parser.
"""

import json
import re
import subprocess
import threading
import time

from .util import exe, have, now_iso

# /usage costs nothing, so a minute is politeness rather than thrift.
REFRESH_SECONDS = 60
ASK_TIMEOUT = 90

# How long a seat may go quiet before the dashboard stops calling it live.
LIVE_SECONDS = 90
IDLE_SECONDS = 15 * 60

# The lines we want out of the /usage report:
#
#   Current session: 5% used · resets Aug 16, 10:30pm (America/Toronto)
#   Current week (all models): 17% used · resets Aug 22, 7am (America/Toronto)
#
# The separator is a middle dot in a UTF-8 terminal and something else wherever
# one could not be encoded, so match anything that is not a word character
# rather than insisting on the dot.
LINE = re.compile(
    r"^[ \t]*Current[ \t]+(?P<label>[^:\n]+?)[ \t]*:[ \t]*"
    r"(?P<percent>\d+(?:\.\d+)?)[ \t]*%[ \t]*used"
    r"(?:[^\w\n]*resets[ \t]+(?P<resets>[^\n]+?))?[ \t]*$",
    re.I | re.M)


def unavailable(reason):
    return {"available": False, "reason": reason, "asked": now_iso(),
            "window": None, "weeks": []}


def parse_usage(text):
    """The /usage report, reduced to the bars the dashboard draws.

    `Current session` *is* the five-hour window - Claude Code calls the window a
    session, which is not the same thing as one conversation. Every `Current
    week` line is kept, because a Max plan reports an all-models week and an
    Opus week separately and either one can be the one that bites.
    """
    buckets = []
    for m in LINE.finditer(text or ""):
        buckets.append({
            "label": m.group("label").strip(),
            "percent": round(float(m.group("percent")), 1),
            "resets": (m.group("resets") or "").strip(),
        })

    window = next((b for b in buckets if b["label"].lower().startswith("session")), None)
    weeks = [b for b in buckets if b["label"].lower().startswith("week")]
    if not window and not weeks:
        return unavailable("Claude answered, but not with a usage report. Run "
                           "`claude` once by hand and finish the login it asks for.")
    return {"available": True, "asked": now_iso(), "window": window, "weeks": weeks}


def ask_claude(root, cmd="claude", timeout=ASK_TIMEOUT):
    """Run `claude -p /usage` in the table and parse what comes back."""
    if not have(cmd):
        return unavailable(f"'{cmd}' is not on your PATH, so there is nobody to ask.")
    try:
        proc = subprocess.run([exe(cmd), "-p", "/usage", "--output-format", "json"],
                              cwd=str(root), input="", capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return unavailable(f"Claude did not answer /usage within {timeout}s.")
    except OSError as e:
        return unavailable(f"Could not run {cmd}: {e}")

    # The slash command's own text arrives as `result`; fall back to raw stdout
    # so a Claude Code that stops wrapping it in JSON still reads fine.
    try:
        data = json.loads((proc.stdout or "").strip() or "{}")
    except json.JSONDecodeError:
        data = {}
    return parse_usage(data.get("result") or proc.stdout or "")


class UsageMeter:
    """Asks once a minute on its own thread; answers the page from cache.

    The dashboard polls /api/state every couple of seconds. Shelling out to
    Claude on each of those would make every page refresh wait on a subprocess,
    so the asking happens on a timer and the page only ever reads the last
    answer.
    """

    def __init__(self, root, cmd="claude", every=REFRESH_SECONDS):
        self.root, self.cmd, self.every = root, cmd, every
        self._lock = threading.Lock()
        self._report = unavailable("Asking Claude what is left...")

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()
        return self

    def _loop(self):
        while True:
            report = ask_claude(self.root, self.cmd)
            with self._lock:
                self._report = report
            time.sleep(self.every)

    def report(self):
        with self._lock:
            return dict(self._report)


def agent_state(installed, idle_seconds):
    """A seat listed in config is a plan, not a pulse. A dashboard that shows a
    seat sitting there long after it stopped answering is worse than one that
    shows nothing."""
    if not installed:
        return "missing"
    if idle_seconds is None:
        return "never"
    if idle_seconds <= LIVE_SECONDS:
        return "live"
    if idle_seconds <= IDLE_SECONDS:
        return "idle"
    return "cold"
