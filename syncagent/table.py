"""The table: a folder, a topic per need, a markdown file per turn.

Everything here is deliberately plain text on disk. There is no database, no
message bus and no daemon - the folder *is* the protocol, which is what lets
three CLIs that share no memory work on the same thing without any of them
re-reading the others' context.
"""

import json
import re
from pathlib import Path

from .util import TABLE, now_iso, read_json, slugify, write_json

# --------------------------------------------------------------------------
# depth - the field that makes "Gemini deep, Claude lighter" real
# --------------------------------------------------------------------------
#
# Depth is measured in bytes sent, not in adjectives in a prompt. A seat set to
# `light` physically does not receive the parts of earlier turns it is not
# meant to re-litigate, which is the only version of this that survives contact
# with a model that likes to be thorough.

DEPTHS = {
    "deep": {
        "label": "deep",
        "prior": "all",          # every earlier turn, in full
        "words": 1200,
        "rule": ("Go as deep as the question deserves. Research it properly, use the "
                 "web where it helps, and show your working. Every factual claim needs "
                 "a source URL in parentheses - no URL means do not make the claim."),
    },
    "light": {
        "label": "light",
        "prior": "findings",     # only the Findings section of earlier turns
        "words": 400,
        "rule": ("Someone has already done the deep pass. Do NOT repeat their research "
                 "and do not restate what they found. Add only what your own judgment "
                 "changes: what they got wrong, what they missed, what you would decide "
                 "differently. Under 400 words."),
        "rule_first": ("You are first, so there is no deep pass to react to. Answer the "
                       "need directly and briefly - the judgment, not the research "
                       "behind it. If answering properly needs work you were not asked "
                       "to do, say so and hand off to a seat that can. Under 600 words."),
    },
    "glance": {
        "label": "glance",
        "prior": "last",         # only the previous turn's findings
        "words": 150,
        "rule": ("You are settling one narrow point, not reviewing the whole topic. "
                 "Give a verdict and the single reason for it. Under 150 words. If the "
                 "question can be settled by running or checking something, say exactly "
                 "what instead of arguing."),
        "rule_first": ("You are first and you have been given only a glance. Say whether "
                       "this needs a deeper seat before anyone spends real effort on it, "
                       "and what specifically they should look at. Under 150 words. Do "
                       "not attempt the whole job yourself."),
    },
}
DEFAULT_DEPTH = "light"

# --------------------------------------------------------------------------
# lenses - the useful half of the old `--track`, chosen per topic
# --------------------------------------------------------------------------
#
# v1 made you pick a track at install time, before you had seen anything work.
# A lens is the same idea reduced to what actually earned its keep: one
# paragraph of focus, swapped into the turn prompt, chosen when you write the
# need and changeable afterwards.

LENSES = {
    "general": {
        "label": "General",
        "focus": ("completeness against what was actually asked, unsupported claims, "
                  "and anything the person will regret not being told."),
    },
    "resume": {
        "label": "Resume / application",
        "focus": ("keyword alignment with the target posting, whether every bullet is "
                  "verifiable against the real base resume, weak verbs, quantification "
                  "gaps, length, and ATS-hostile formatting.\n\n"
                  "TRUTH CONSTRAINT: tailoring sharpens what is true, it does not invent. "
                  "If a suggested bullet cannot be traced to something in the base resume, "
                  "say so explicitly rather than writing it. Inventing experience is the "
                  "one failure mode here that actually costs someone an interview."),
    },
    "code": {
        "label": "Code",
        "focus": ("correctness, edge cases, error handling, security, and whether the "
                  "change does what it claims. Every finding must cite a file and a line - "
                  "a finding without a location is discarded unread, so do not write it."),
    },
    "writing": {
        "label": "Writing",
        "focus": ("argument structure, unsupported claims, repetition, citation "
                  "completeness, and whether the piece says anything the reader could "
                  "not have guessed."),
    },
    "decision": {
        "label": "Decision",
        "focus": ("the options actually available, what each one costs, what would have "
                  "to be true for each to be right, and which evidence would change the "
                  "answer. Name a recommendation - a balanced survey is not a decision."),
    },
}
DEFAULT_LENS = "general"

STATUSES = ("queued", "running", "done", "failed", "skipped")


# --------------------------------------------------------------------------
# finding the table
# --------------------------------------------------------------------------

def find_table(start=None):
    """Walk upward looking for a `table/` directory. None if there is none."""
    p = Path(start or Path.cwd()).resolve()
    for candidate in [p, *p.parents]:
        if (candidate / TABLE).is_dir():
            return candidate
    return None


def table_dir(root):
    return Path(root) / TABLE


CONFIG_VERSION = "2.2"


def default_config():
    """The shape written on first run.

    Seats are ordered: the relay runs them in this order, cheapest and deepest
    first, so that the scarce Claude quota is spent on a turn that already has
    something to react to.
    """
    return {
        "version": CONFIG_VERSION,
        "created": now_iso(),
        "auto_relay": True,
        "max_hops": 3,
        "seats": {
            # Google withdrew the Gemini CLI's individual free tier, so the
            # research chair is Antigravity's `agy` running a Gemini model.
            # The plain `gemini` seat below still works if you have an API key
            # or a paid Code Assist plan - enable it there.
            "antigravity": {
                "cmd": "agy",
                "model": "gemini-3.1-pro-high",
                "depth": "deep",
                "role": "research and evidence",
                "order": 1,
                "enabled": True,
                "scribe": False,
            },
            "gemini": {
                "cmd": "gemini",
                "model": "",
                "depth": "deep",
                "role": "research and evidence",
                "order": 1,
                "enabled": False,
                "scribe": False,
            },
            "claude": {
                "cmd": "claude",
                "model": "",
                "depth": "light",
                "role": "judgment and critique",
                "order": 2,
                "enabled": True,
                "scribe": True,
            },
            "codex": {
                "cmd": "codex",
                "model": "",
                "depth": "glance",
                "role": "tiebreak, on request",
                "order": 3,
                "enabled": True,
                "on_call": True,
                "scribe": False,
            },
        },
    }


def migrate_config(cfg):
    """Bring an existing config up to the current shape. (cfg, changed, notes).

    An existing table used to be frozen at whatever the defaults were the day it
    was created: seats added later never appeared in it, so a table made before
    Antigravity existed kept trying to run the withdrawn Gemini CLI forever.
    A config on disk is the user's, so this only ever *adds* what is missing and
    turns off a seat that is known not to work - it never re-enables, reorders
    or renames anything the user has set.
    """
    base = default_config()
    notes = []
    changed = False

    for key, value in base.items():
        if key not in cfg:
            cfg[key] = value
            changed = True

    seats = cfg.setdefault("seats", {})
    for name, seat in base["seats"].items():
        if name not in seats:
            seats[name] = dict(seat)
            changed = True
            if seat.get("enabled", True):
                notes.append(f"added the '{name}' seat")
        else:
            merged = dict(seat)
            merged.update(seats[name])
            seats[name] = merged

    if cfg.get("version") != CONFIG_VERSION:
        # 2.0 -> 2.1: Google withdrew the Gemini CLI's individual free tier, so
        # a `gemini` seat left enabled sits at the front of the relay and fails
        # every topic. Stand it down in favour of the seat that replaced it,
        # and say so rather than doing it silently.
        gem = seats.get("gemini")
        if (gem and gem.get("enabled")
                and seats.get("antigravity", {}).get("enabled")):
            gem["enabled"] = False
            gem["disabled_reason"] = (
                "Google withdrew the Gemini CLI's individual free tier. Set "
                "GEMINI_API_KEY or GOOGLE_CLOUD_PROJECT and set enabled back to "
                "true if you have a paid plan.")
            notes.append("stood down the 'gemini' seat, which can no longer answer")

        # 2.1 -> 2.2: the budget gauge asks `claude -p /usage` for the real
        # percentages instead of weighting tokens against a guessed ceiling, so
        # the hand-tuned limits nobody could verify are no longer read by
        # anything. Leaving dead knobs in a config file is its own kind of lie.
        if cfg.pop("limits", None) is not None:
            notes.append("dropped the guessed token ceilings - Claude is asked directly now")

        cfg["version"] = CONFIG_VERSION
        changed = True

    return cfg, changed, notes


def load_config(root, save=True):
    path = table_dir(root) / "config.json"
    stored = read_json(path, None)
    if not isinstance(stored, dict):
        return default_config()
    cfg, changed, notes = migrate_config(stored)
    if changed and save:
        try:
            write_json(path, cfg)
            if notes:
                print(f"table/config.json updated: {'; '.join(notes)}.")
        except OSError:
            pass
    return cfg


def save_config(root, cfg):
    write_json(table_dir(root) / "config.json", cfg)


def seat_order(cfg):
    """Enabled seats in relay order, excluding the on-call ones."""
    seats = cfg.get("seats", {})
    live = [(name, s) for name, s in seats.items()
            if s.get("enabled", True) and not s.get("on_call")]
    live.sort(key=lambda pair: (pair[1].get("order", 99), pair[0]))
    return [name for name, _ in live]


def scribe(cfg):
    for name, s in (cfg.get("seats") or {}).items():
        if s.get("scribe") and s.get("enabled", True):
            return name
    return None


# --------------------------------------------------------------------------
# telemetry
# --------------------------------------------------------------------------

def log_event(root, record):
    record["ts"] = now_iso()
    path = table_dir(root) / "telemetry.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_telemetry(root):
    path = table_dir(root) / "telemetry.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# --------------------------------------------------------------------------
# topics
# --------------------------------------------------------------------------

TOPIC_RE = re.compile(r"^(\d{3})-")


def list_topic_dirs(root):
    td = table_dir(root)
    if not td.is_dir():
        return []
    return sorted((d for d in td.iterdir()
                   if d.is_dir() and TOPIC_RE.match(d.name)),
                  key=lambda d: d.name)


def next_topic_number(root):
    """One higher than any number ever issued - never a count, never a re-use.

    Scanning the folders alone is not enough: delete or archive topic 002 and a
    scan hands 002 straight back out, so two different topics end up sharing an
    id in filenames and telemetry. The high-water mark is therefore persisted
    alongside the scan, and the larger of the two wins.
    """
    highest = 0
    for d in list_topic_dirs(root):
        m = TOPIC_RE.match(d.name)
        if m:
            highest = max(highest, int(m.group(1)))

    counter = table_dir(root) / "counter.json"
    issued = int(read_json(counter, {}).get("last_topic") or 0)
    number = max(highest, issued) + 1
    write_json(counter, {"last_topic": number})
    return number


def topic_dir(root, topic_id):
    return table_dir(root) / topic_id


def load_topic(root, topic_id):
    doc = read_json(topic_dir(root, topic_id) / "topic.json", None)
    return doc if isinstance(doc, dict) else None


def save_topic(root, topic):
    topic["updated"] = now_iso()
    write_json(topic_dir(root, topic["id"]) / "topic.json", topic)


def all_topics(root):
    out = []
    for d in list_topic_dirs(root):
        doc = load_topic(root, d.name)
        if doc:
            out.append(doc)
    out.sort(key=lambda t: t.get("id", ""), reverse=True)
    return out


def create_topic(root, need, lens=DEFAULT_LENS, steps=None, cfg=None):
    """Write the topic folder: NEED.md, BRIEF.md, topic.json.

    `steps` is the plan - who does what, in order. When it is None the relay
    order from config is used, which is the "just answer it" path.
    """
    cfg = cfg or load_config(root)
    lens = lens if lens in LENSES else DEFAULT_LENS
    number = next_topic_number(root)
    topic_id = f"{number:03d}-{slugify(need)}"
    d = topic_dir(root, topic_id)
    d.mkdir(parents=True, exist_ok=True)

    if not steps:
        steps = [{"seat": name,
                  "job": (cfg["seats"][name].get("role") or "take a look"),
                  "depth": cfg["seats"][name].get("depth", DEFAULT_DEPTH)}
                 for name in seat_order(cfg)]

    plan = []
    for i, step in enumerate(steps, start=1):
        plan.append({
            "n": i,
            "seat": step.get("seat"),
            "job": step.get("job") or "take a look",
            "depth": step.get("depth") or DEFAULT_DEPTH,
            "status": "queued",
            "file": None,
            "started": None,
            "finished": None,
            "tokens": {},
            "handoff": None,
            "error": None,
        })

    topic = {
        "id": topic_id,
        "need": need,
        "lens": lens,
        "created": now_iso(),
        "status": "open",
        "hops": 0,
        "steps": plan,
        "sessions": {},
    }

    (d / "NEED.md").write_text(f"# {need}\n", encoding="utf-8")
    (d / "BRIEF.md").write_text(build_brief(root, topic), encoding="utf-8")
    save_topic(root, topic)
    log_event(root, {"kind": "topic", "topic": topic_id, "lens": lens,
                     "steps": [s["seat"] for s in plan]})
    return topic


BRIEF_CAP = 6000


def build_brief(root, topic):
    """The one document every seat reads, whatever its depth.

    Capped hard. The cap is the point: a brief that grows without limit is just
    the conversation again, and re-sending the conversation to three CLIs is
    exactly the cost this tool exists to avoid.
    """
    lens = LENSES.get(topic.get("lens"), LENSES[DEFAULT_LENS])
    inputs = list_inputs(root)
    lines = [
        "# Brief",
        "",
        "## The need",
        "",
        topic.get("need", "").strip(),
        "",
        f"## Lens: {lens['label']}",
        "",
        "What matters here:",
        "",
        lens["focus"],
        "",
    ]
    if inputs:
        lines += [
            "## Material on the table",
            "",
            "These files are in `table/inputs/`. Read the ones you need; they are",
            "read-only. Do not ask for them to be pasted to you.",
            "",
        ]
        lines += [f"- `table/inputs/{p}`" for p in inputs]
        lines.append("")
    text = "\n".join(lines)
    return text[:BRIEF_CAP]


def list_inputs(root):
    d = table_dir(root) / "inputs"
    if not d.is_dir():
        return []
    return sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file())


# --------------------------------------------------------------------------
# turn files and the handoff block
# --------------------------------------------------------------------------

def turn_filename(step):
    job = slugify(step.get("job", ""), limit=24) or "turn"
    return f"{step['n']:02d}-{step['seat']}-{job}.md"


def section(markdown, heading):
    """The body of one `## Heading` section, or '' if it is not there.

    Tolerates `#`/`##`/`###`, surrounding whitespace and a trailing colon,
    because models are inconsistent about all three and a strict match here
    would silently drop the content depth slicing depends on.
    """
    pattern = re.compile(
        r"^\s{0,3}#{1,4}\s*" + re.escape(heading) + r"\s*:?\s*$(.*?)(?=^\s{0,3}#{1,4}\s|\Z)",
        re.S | re.M | re.I)
    m = pattern.search(markdown or "")
    return m.group(1).strip() if m else ""


HANDOFF_FIELD = re.compile(r"^\s*[-*]?\s*(to|job|why)\s*:\s*(.*?)\s*$", re.I | re.M)

# What a seat is likely to call another seat, versus what the config calls it.
# A handoff that names the binary instead of the seat is a naming quibble, not
# a refusal, so it should not cost a turn.
SEAT_ALIASES = {
    "agy": "antigravity",
    "antigrav": "antigravity",
    "gemini3": "antigravity",
    "claudecode": "claude",
    "openai": "codex",
    "gpt": "codex",
}


def parse_handoff(markdown, known_seats=()):
    """The `## Handoff` block at the end of a turn, as a dict.

    Returns None when there is no usable block. A handoff naming a seat that
    does not exist is downgraded to `user` rather than dropped: the seat's
    reasoning about what should happen next is still worth showing, it just
    cannot be dispatched.
    """
    body = section(markdown, "Handoff")
    if not body:
        return None
    found = {}
    for key, value in HANDOFF_FIELD.findall(body):
        found.setdefault(key.lower(), value.strip())
    to = (found.get("to") or "").strip().lower()
    to = re.sub(r"[^a-z]", "", to.split()[0]) if to.split() else ""
    if not to:
        return None
    handoff = {
        "to": to,
        "job": found.get("job", "").strip(),
        "why": found.get("why", "").strip(),
        "dispatchable": True,
    }
    if to in ("none", "user", "human", "me"):
        handoff["to"] = "user" if to != "none" else "none"
        handoff["dispatchable"] = False
        return handoff

    if to not in (known_seats or ()) and to in SEAT_ALIASES:
        to = handoff["to"] = SEAT_ALIASES[to]

    if known_seats and to not in known_seats:
        handoff["unknown_seat"] = to
        handoff["to"] = "user"
        handoff["dispatchable"] = False
    return handoff


def prior_turns(root, topic, upto_n, depth):
    """What an earlier turn looks like to this one, at this depth.

    This function is the whole token argument. `deep` sees everything, `light`
    sees only what each seat concluded, `glance` sees only the turn immediately
    before it. Nothing here ever includes the repository or the raw inputs.
    """
    rule = DEPTHS.get(depth, DEPTHS[DEFAULT_DEPTH])["prior"]
    done = [s for s in topic.get("steps", [])
            if s.get("status") == "done" and s.get("file") and s["n"] < upto_n]
    if not done:
        return ""
    if rule == "last":
        done = done[-1:]

    d = topic_dir(root, topic["id"])
    blocks = []
    for step in done:
        try:
            text = (d / step["file"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        header = f"### {step['seat']} - {step.get('job', '')} ({step.get('depth')})"
        if rule == "all":
            body = text.strip()
        else:
            body = section(text, "Findings") or _first_paragraphs(text)
        if body:
            blocks.append(f"{header}\n\n{body}")
    if not blocks:
        return ""
    return "\n\n".join(blocks)


def _first_paragraphs(text, limit=1200):
    """Fallback when a seat ignored the Findings heading. Better than sending
    the whole turn to a seat that was told not to read the whole turn."""
    stripped = re.sub(r"^\s{0,3}#{1,4}\s*Handoff\s*:?\s*$.*", "", text or "",
                      flags=re.S | re.M | re.I)
    return stripped.strip()[:limit]
