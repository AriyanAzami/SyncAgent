"""Small shared helpers. No SyncAgent concepts live here - only plumbing."""

import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

TABLE = "table"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_ts(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def write_json(path, obj):
    """Write via a sibling temp file so a crash mid-write cannot leave a
    half-written topic.json behind - the runner rewrites these on every turn."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# Where a CLI installs itself when it does not put itself on PATH.
# Antigravity's `agy` is the current example: it ships an `agy install`
# subcommand to edit your shell profile, so a freshly installed and fully
# logged-in CLI is invisible to `which` until you run that and open a new
# terminal. Looking in its own install directory costs nothing and removes a
# confusing "not installed" for a tool the user can plainly see working.
EXTRA_BIN_DIRS = {
    "agy": [
        Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin",
        Path.home() / ".agy" / "bin",
        Path.home() / ".local" / "bin",
        Path("/usr/local/bin"),
    ],
}


def find_binary(name):
    """Full path to a CLI, or None. Checks PATH first, then known homes."""
    found = shutil.which(name)
    if found:
        return found
    for d in EXTRA_BIN_DIRS.get(name, []):
        try:
            for candidate in (d / name, d / f"{name}.exe", d / f"{name}.cmd"):
                if candidate.is_file():
                    return str(candidate)
        except OSError:
            continue
    return None


def have(binary):
    return find_binary(binary) is not None


def exe(binary):
    """Resolve a CLI to a full path before launching it.

    On Windows several of these CLIs are npm shims - `gemini.CMD`, not
    `gemini.exe`. shutil.which() finds them because it honours PATHEXT, but
    CreateProcess only ever appends `.exe` when it searches PATH, so passing
    the bare name to subprocess raises FileNotFoundError on a machine where the
    CLI is plainly installed. Hand it the resolved path instead.
    """
    return find_binary(binary) or binary


def cli_invocation():
    """How to invoke this tool from anywhere, with this machine's interpreter.

    macOS frequently has no `python` at all - Homebrew and python.org both
    install `python3` only - and the table is usually not the folder the code
    lives in, so neither half of `python syncagent.py` can be assumed.
    """
    entry = Path(__file__).resolve().parent.parent / "sync.py"
    py = sys.executable or "python3"
    quote = lambda s: f'"{s}"' if " " in str(s) else str(s)
    return f"{quote(py)} {quote(entry)}"


def slugify(text, limit=40):
    """A short, filesystem-safe stem for a topic folder."""
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    if len(s) > limit:
        s = s[:limit].rsplit("-", 1)[0] or s[:limit]
    return s or "topic"


def strip_fences(text):
    """Models wrap output in ``` fences even when told not to."""
    t = (text or "").strip()
    m = re.match(r"^```[A-Za-z0-9_+-]*\s*\n(.*?)\n?```$", t, re.S)
    return m.group(1).strip() if m else t


def meter_bar(percent, width=28):
    lit = int(round(min(percent, 100) / 100 * width))
    return "[" + "#" * lit + "." * (width - lit) + "]"
