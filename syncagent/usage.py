"""Measured Claude token spend, read straight off the local session transcripts.

Claude Code appends every assistant turn, with the exact usage block the API
returned, to ~/.claude/projects/<slugged-cwd>/<session-id>.jsonl. That file is
the only real-time source of truth for what a session has actually spent - a
self-report is something the model has to remember to make, and a self-report
always undercounts.

Lifted from SyncAgent 1.x unchanged. tests/test_usage.py is the regression guard.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .util import parse_ts, read_json

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"

# Subscription limits are consumption budgets, not message counts, and the four
# token classes are nowhere near equal: a cached read costs a tenth of a fresh
# input token and an output token costs five times one. Weighting each class by
# its relative price is what makes a single "how much is left" number honest.
TOKEN_WEIGHTS = {"input": 1.0, "output": 5.0, "cache_write": 1.25, "cache_read": 0.1}

# Anthropic does not publish the subscription ceilings in tokens, so these are
# calibrated estimates rather than quoted figures. They live in config.json
# exactly so that a user who hits a limit at 60% can correct them.
PLAN_LIMITS = {
    "pro":     {"window":  2_000_000, "weekly":  25_000_000},
    "max-5x":  {"window": 10_000_000, "weekly": 125_000_000},
    "max-20x": {"window": 40_000_000, "weekly": 500_000_000},
}
DEFAULT_LIMITS = {
    "plan": "max-5x",
    "window_hours": 5,
    "window_tokens": PLAN_LIMITS["max-5x"]["window"],
    "weekly_tokens": PLAN_LIMITS["max-5x"]["weekly"],
    "weights": TOKEN_WEIGHTS,
}
USAGE_KEYS = ("input", "output", "cache_write", "cache_read", "total", "weighted")

# How long a seat may go quiet before the dashboard stops calling it live.
LIVE_SECONDS = 90
IDLE_SECONDS = 15 * 60


def project_slug(path):
    return re.sub(r"[^A-Za-z0-9]", "-", str(Path(path).resolve()))


def _transcript_cwd(path, max_lines=60):
    """The workspace a transcript belongs to, as it recorded it itself."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= max_lines:
                    break
                if '"cwd"' not in line:
                    continue
                try:
                    cwd = json.loads(line).get("cwd")
                except json.JSONDecodeError:
                    continue
                if cwd:
                    return str(Path(cwd)).lower()
    except OSError:
        pass
    return None


def transcript_dir(root):
    direct = CLAUDE_PROJECTS / project_slug(root)
    if direct.is_dir():
        return direct
    # The slug rule has changed between Claude Code versions. Rather than guess
    # at it, ask the transcripts which one recorded this workspace.
    if not CLAUDE_PROJECTS.is_dir():
        return None
    target = str(Path(root).resolve()).lower()
    for d in sorted(CLAUDE_PROJECTS.iterdir()):
        if not d.is_dir():
            continue
        for f in d.glob("*.jsonl"):
            if _transcript_cwd(f) == target:
                return d
    return None


def _usage_record(entry, weights):
    msg = entry.get("message") or {}
    u = msg.get("usage")
    ts = parse_ts(entry.get("timestamp"))
    if not isinstance(u, dict) or ts is None:
        return None
    counts = {
        "input": int(u.get("input_tokens") or 0),
        "output": int(u.get("output_tokens") or 0),
        "cache_write": int(u.get("cache_creation_input_tokens") or 0),
        "cache_read": int(u.get("cache_read_input_tokens") or 0),
    }
    rec = dict(counts)
    rec["total"] = sum(counts.values())
    rec["weighted"] = round(sum(counts[k] * weights.get(k, 1.0) for k in counts))
    rec["ts"] = ts
    rec["session"] = entry.get("sessionId") or ""
    rec["model"] = msg.get("model") or "unknown"
    return rec


def read_claude_usage(root, weights=None):
    """Every assistant turn this workspace has produced, deduplicated.

    Resumed and forked sessions copy earlier turns into the new transcript, so
    the same API call appears in several files. Keying on the message id counts
    each call exactly once.
    """
    weights = weights or TOKEN_WEIGHTS
    d = transcript_dir(root)
    if not d:
        return []
    seen, out = set(), []
    for f in sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime):
        try:
            fh = open(f, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"usage"' not in line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "assistant":
                    continue
                key = (entry.get("message") or {}).get("id") or entry.get("requestId")
                if key:
                    if key in seen:
                        continue
                    seen.add(key)
                rec = _usage_record(entry, weights)
                if rec:
                    out.append(rec)
    out.sort(key=lambda r: r["ts"])
    return out


def _sum_usage(records):
    agg = {k: sum(r[k] for r in records) for k in USAGE_KEYS}
    agg["calls"] = len(records)
    agg["first"] = records[0]["ts"].isoformat() if records else None
    agg["last"] = records[-1]["ts"].isoformat() if records else None
    return agg


def _bucket(records, used, limit, now, window=None):
    """A spend bucket plus the two numbers a human actually wants: what fraction
    of the ceiling is gone, and when the ceiling stops applying."""
    block = _sum_usage(records)
    block["limit"] = limit
    block["remaining"] = max(limit - used, 0) if limit else 0
    block["percent"] = round(min(used / limit, 1.0) * 100, 1) if limit else 0.0
    block["over"] = bool(limit and used > limit)
    if window and records:
        block["resets"] = (records[0]["ts"] + window).isoformat()
        block["resets_in_hours"] = round(
            max((records[0]["ts"] + window - now).total_seconds(), 0) / 3600, 2)
    else:
        block["resets"] = None
        block["resets_in_hours"] = None
    return block


def resolve_limits(cfg):
    """Config wins over the plan preset, the preset wins over the default."""
    configured = cfg.get("limits") or {}
    limits = dict(DEFAULT_LIMITS)
    preset = PLAN_LIMITS.get(configured.get("plan", limits["plan"]))
    if preset:
        limits["window_tokens"] = preset["window"]
        limits["weekly_tokens"] = preset["weekly"]
    limits.update(configured)
    weights = dict(TOKEN_WEIGHTS)
    weights.update(limits.get("weights") or {})
    limits["weights"] = weights
    return limits


def claude_usage_report(root, cfg=None):
    """What this workspace has spent, over the three windows that matter: the
    live session, the rolling subscription window, and the week."""
    cfg = cfg if cfg is not None else {}
    limits = resolve_limits(cfg)
    weights = limits["weights"]
    records = read_claude_usage(root, weights)

    now = datetime.now(timezone.utc)
    window = timedelta(hours=float(limits.get("window_hours") or 5))
    win_limit = int(limits.get("window_tokens") or 0)
    week_limit = int(limits.get("weekly_tokens") or 0)

    report = {
        "available": bool(records),
        "source": str(transcript_dir(root) or ""),
        "plan": limits.get("plan", "custom"),
        "window_hours": window.total_seconds() / 3600,
        "weights": weights,
        "estimated_limits": True,
        "updated": now.isoformat(timespec="seconds"),
    }
    if not records:
        report["reason"] = ("No Claude Code transcripts found for this table. "
                            "Run Claude from inside it and the meter fills itself.")
        return report

    in_window = [r for r in records if r["ts"] >= now - window]
    in_week = [r for r in records if r["ts"] >= now - timedelta(days=7)]
    in_day = [r for r in records if r["ts"] >= now - timedelta(days=1)]

    win_used = sum(r["weighted"] for r in in_window)
    week_used = sum(r["weighted"] for r in in_week)

    session_id = records[-1]["session"]
    session = [r for r in records if r["session"] == session_id]

    report["session"] = _sum_usage(session)
    report["session"]["id"] = session_id
    report["day"] = _sum_usage(in_day)
    report["window"] = _bucket(in_window, win_used, win_limit, now, window)
    report["week"] = _bucket(in_week, week_used, week_limit, now, timedelta(days=7))

    # Burn rate from the last hour, because that is what "how much longer can I
    # keep working" depends on. With too little recent traffic to extrapolate
    # from, fall back to the average across the whole window.
    recent = [r for r in records if r["ts"] >= now - timedelta(hours=1)]
    if len(recent) >= 2:
        burn = sum(r["weighted"] for r in recent)
    elif in_window:
        elapsed = max((now - in_window[0]["ts"]).total_seconds() / 3600, 0.05)
        burn = win_used / elapsed
    else:
        burn = 0.0
    report["burn_per_hour"] = round(burn)

    hours_left = None
    if burn > 0:
        candidates = [b["remaining"] / burn for b in (report["window"], report["week"])
                      if b["limit"]]
        if candidates:
            hours_left = min(candidates)
    report["hours_left"] = round(hours_left, 2) if hours_left is not None else None
    report["runs_out"] = ((now + timedelta(hours=hours_left)).isoformat(timespec="seconds")
                          if hours_left is not None else None)
    report["binding"] = ("week" if report["week"]["limit"] and report["window"]["limit"]
                         and report["week"]["percent"] > report["window"]["percent"]
                         else "window")

    by_model = {}
    for r in session:
        blank = dict.fromkeys(USAGE_KEYS, 0)
        blank["calls"] = 0
        m = by_model.setdefault(r["model"], blank)
        for k in USAGE_KEYS:
            m[k] += r[k]
        m["calls"] += 1
    report["by_model"] = by_model
    return report


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
