"""Command line. Running it with no arguments is the whole intended path."""

import argparse
import sys
from pathlib import Path

from . import prompts as P
from . import seats as S
from . import table as T
from .server import health_path, serve
from .usage import PLAN_LIMITS, claude_usage_report
from .util import TABLE, fmt_hours, have, meter_bar, now_iso, write_json

SEAT_HELP = {
    "antigravity": "https://antigravity.google  (the `agy` CLI)",
    "claude": "https://docs.claude.com/en/docs/claude-code/setup",
    "gemini": "https://github.com/google-gemini/gemini-cli",
    "codex": "https://github.com/openai/codex",
}


# --------------------------------------------------------------------------
# setup
# --------------------------------------------------------------------------

def make_table(root, quiet=False):
    """Create `table/` and everything in it. Safe to re-run."""
    root = Path(root).resolve()
    td = root / TABLE
    for sub in ("", "inputs", "out", "prompts"):
        (td / sub).mkdir(parents=True, exist_ok=True)

    cfg_path = td / "config.json"
    if not cfg_path.exists():
        cfg = T.default_config()
        for name, seat in cfg["seats"].items():
            # A missing binary disables a seat, but a seat the defaults turned
            # off stays off - `gemini` ships disabled because its individual
            # free tier was withdrawn, and finding the binary is not evidence
            # that it can answer.
            seat["enabled"] = seat.get("enabled", True) and have(seat["cmd"])
        write_json(cfg_path, cfg)

    turn = td / "prompts" / "turn.md"
    if not turn.exists():
        turn.write_text(P.TURN_TEMPLATE, encoding="utf-8")

    readme = td / "inputs" / "README.md"
    if not readme.exists():
        readme.write_text(
            "# inputs\n\nDrop material here: a resume, a job posting, a spec, a "
            "draft.\n\nEvery seat can read this folder and none of them may write "
            "to it. Files here are listed in the brief, so you never paste the "
            "same thing into three different chats.\n", encoding="utf-8")

    out_readme = td / "out" / "README.md"
    if not out_readme.exists():
        out_readme.write_text(
            "# out\n\nReal deliverables land here.\n\nOnly the scribe seat can "
            "write to this folder. Every other seat advises only.\n",
            encoding="utf-8")

    # Deny rules are evaluated before the permission mode, so they hold even for
    # the scribe seat, which runs with edits auto-accepted.
    settings = root / ".claude" / "settings.json"
    if not settings.exists():
        settings.parent.mkdir(parents=True, exist_ok=True)
        write_json(settings, {
            "$schema": "https://json.schemastore.org/claude-code-settings.json",
            "permissions": {
                "deny": [
                    f"Edit(./{TABLE}/inputs/**)",
                    f"Write(./{TABLE}/inputs/**)",
                    f"Edit(./{TABLE}/telemetry.jsonl)",
                    f"Write(./{TABLE}/telemetry.jsonl)",
                    "Read(./.env)", "Read(./.env.*)", "Read(./secrets/**)",
                    "Bash(rm -rf /*)", "Bash(sudo *)", "Bash(curl *|*sh)",
                ],
                "ask": ["Bash(git push*)", "Bash(npm publish*)", "Bash(gh release*)"],
            },
        })

    # Ignore the whole table, not selected files inside it.
    #
    # A table created in a git repo otherwise fills `git status` with topic
    # folders and turn files - your working state, not the project's source.
    # Anyone who does want to share a table can still `git add -f` it.
    gi = root / ".gitignore"
    entries = [f"{TABLE}/"]
    existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
    missing = [e for e in entries if e not in existing]
    if missing:
        with open(gi, "a", encoding="utf-8") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            fh.write("\n".join(missing) + "\n")

    if not quiet:
        print(f"  Table ready at {td}")
    return root


def wizard(start=None):
    """First run. Short by design - four lines of output and a folder."""
    here = Path(start or Path.cwd()).resolve()
    print()
    print("  SyncAgent - a table your AI agents sit around.")
    print()
    print("  Seats found on this machine:")
    found = 0
    for name in ("antigravity", "claude", "codex"):
        if have(T.default_config()["seats"][name]["cmd"]):
            found += 1
            print(f"    {name:<12} ready")
        else:
            print(f"    {name:<12} not installed   {SEAT_HELP[name]}")
    print()
    if not found:
        print("  None of the three CLIs are installed, so no seat could answer.")
        print("  Install at least one, then run this again.")
        sys.exit(1)

    print(f"  The table will live in: {here / TABLE}")
    try:
        reply = input("  Press enter to accept, or type another folder: ").strip()
    except EOFError:
        reply = ""
    root = Path(reply).expanduser().resolve() if reply else here
    root.mkdir(parents=True, exist_ok=True)
    make_table(root)
    print()
    print("  Next: drop anything the agents should read into "
          f"{Path(TABLE) / 'inputs'}, then type your need on the dashboard.")
    return root


def resolve_root(explicit=None, allow_wizard=True):
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if not (root / TABLE).is_dir():
            make_table(root)
        return root
    root = T.find_table()
    if root:
        return root
    if not allow_wizard:
        sys.exit(f"No `{TABLE}/` folder here or above. Run this with no arguments "
                 f"to create one.")
    return wizard()


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_dash(args):
    root = resolve_root(args.path)
    serve(root, port=args.port, open_browser=not args.no_browser)


def cmd_ask(args):
    """Put a need on the table from the terminal and watch it run."""
    from .runner import Runner

    root = resolve_root(args.path)
    cfg = T.load_config(root)
    steps = None
    if args.seat:
        steps = [{"seat": s, "depth": args.depth
                  or cfg["seats"].get(s, {}).get("depth", T.DEFAULT_DEPTH),
                  "job": cfg["seats"].get(s, {}).get("role", "take a look")}
                 for s in args.seat]
    topic = T.create_topic(root, args.need, lens=args.lens, steps=steps, cfg=cfg)
    print(f"topic {topic['id']}  ({len(topic['steps'])} steps: "
          f"{' -> '.join(s['seat'] for s in topic['steps'])})")

    runner = Runner(root)
    runner.enqueue(topic["id"], topic["steps"][0]["n"])
    seen = set()
    while True:
        runner.q.join()
        current = T.load_topic(root, topic["id"])
        for s in current["steps"]:
            key = (s["n"], s["status"])
            if s["status"] in ("done", "failed", "skipped") and key not in seen:
                seen.add(key)
                mark = {"done": "  ", "failed": "! ", "skipped": "- "}[s["status"]]
                detail = s.get("file") or s.get("error") or ""
                print(f"{mark}{s['seat']:<8} {s['status']:<8} {detail}")
        if runner.q.empty() and not runner.state()["running"]:
            break
    d = T.topic_dir(root, topic["id"])
    if (d / "ANSWER.md").exists():
        print(f"\n{(d / 'ANSWER.md')}\n")
        print((d / "ANSWER.md").read_text(encoding="utf-8"))
    else:
        print(f"\nTurns are in {d}")


def cmd_doctor(args):
    root = resolve_root(args.path, allow_wizard=False)
    cfg = T.load_config(root)
    print("Checking each seat with a one-word call. This costs a few tokens.\n")
    results = {}
    worst = 0
    for name, seat in (cfg.get("seats") or {}).items():
        if not seat.get("enabled", True):
            print(f"  {name:<12} disabled in config.json")
            continue
        r = S.check_seat(name, seat, root)
        results[name] = r
        if r["state"] == "ready":
            print(f"  {name:<12} ready   {r.get('detail', '')}")
        else:
            worst = 1
            print(f"  {name:<12} {r['state'].upper():<7} {r['detail']}")
    write_json(health_path(root), {"checked": now_iso(), "seats": results})
    if worst:
        print("\nA blocked seat still shows on the dashboard - it just cannot take a turn.")
    sys.exit(worst)


def cmd_usage(args):
    root = resolve_root(args.path, allow_wizard=False)
    cfg = T.load_config(root)
    if args.plan or args.window_tokens or args.weekly_tokens:
        limits = dict(cfg.get("limits") or {})
        if args.plan:
            limits["plan"] = args.plan
            preset = PLAN_LIMITS.get(args.plan)
            if preset:
                limits["window_tokens"] = preset["window"]
                limits["weekly_tokens"] = preset["weekly"]
        if args.window_tokens:
            limits["window_tokens"] = args.window_tokens
        if args.weekly_tokens:
            limits["weekly_tokens"] = args.weekly_tokens
        cfg["limits"] = limits
        T.save_config(root, cfg)
        print("limits updated in table/config.json")

    u = claude_usage_report(root, cfg)
    if args.json:
        import json
        print(json.dumps(u, indent=2))
        return
    if not u.get("available"):
        print(u.get("reason", "No measured Claude usage yet."))
        return

    s, w, k = u["session"], u["window"], u["week"]
    print(f"plan {u['plan']}  -  weighted tokens (output x{u['weights']['output']:g}, "
          f"cache read x{u['weights']['cache_read']:g})")
    print()
    print(f"this session   {s['calls']:>4} calls  {s['total']:>12,} raw  "
          f"{s['weighted']:>12,} weighted")
    print()
    win_label = f"{u['window_hours']:g}h window"
    print(f"{win_label:<14} {meter_bar(w['percent'])} {w['percent']:>5.1f}%"
          f"   {w['weighted']:,} / {w['limit']:,}")
    print(f"{'':<14} resets in {fmt_hours(w['resets_in_hours'])}")
    print(f"{'7d window':<14} {meter_bar(k['percent'])} {k['percent']:>5.1f}%"
          f"   {k['weighted']:,} / {k['limit']:,}")
    print()
    print(f"burn rate      {u['burn_per_hour']:,} weighted tok/hour")
    print(f"headroom       {fmt_hours(u['hours_left'])} of work left "
          f"(binding limit: {u['binding']})")
    print()
    print("Ceilings are estimates - Anthropic does not publish them in tokens.")


def cmd_setup(args):
    root = Path(args.path).expanduser().resolve() if args.path else None
    if root:
        root.mkdir(parents=True, exist_ok=True)
        make_table(root)
    else:
        wizard()


def cmd_list(args):
    root = resolve_root(args.path, allow_wizard=False)
    topics = T.all_topics(root)
    if not topics:
        print("Nothing on the table.")
        return
    for t in topics:
        done = sum(1 for s in t["steps"] if s["status"] == "done")
        tok = sum((s.get("tokens") or {}).get("total", 0) for s in t["steps"])
        print(f"  {t['id']:<44} {t['status']:<9} {done}/{len(t['steps'])} turns  "
              f"{tok:>8,} tok")


# --------------------------------------------------------------------------

def main(argv=None):
    # --path is offered on the top level and on every subcommand, because
    # `sync setup --path x` is what anyone would type and argparse otherwise
    # only accepts it before the subcommand. SUPPRESS keeps the subcommand copy
    # from clobbering a value given in the earlier position with None.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--path", default=argparse.SUPPRESS,
                        help="the folder holding table/ (default: search upward)")

    ap = argparse.ArgumentParser(
        prog="sync", parents=[common],
        description="A table your AI agents sit around. Run with no arguments.")
    ap.set_defaults(path=None)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("dash", parents=[common], help="open the dashboard (the default)")
    p.add_argument("--port", type=int, default=7777)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(func=cmd_dash)

    p = sub.add_parser("ask", parents=[common], help="put a need on the table from the terminal")
    p.add_argument("need")
    p.add_argument("--lens", default=T.DEFAULT_LENS, choices=sorted(T.LENSES))
    p.add_argument("--seat", action="append",
                   help="run only this seat; repeat to set the order")
    p.add_argument("--depth", choices=sorted(T.DEPTHS))
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("doctor", parents=[common], help="check every seat with one tiny call")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("usage", parents=[common], help="measured Claude spend and headroom")
    p.add_argument("--json", action="store_true")
    p.add_argument("--plan", choices=sorted(PLAN_LIMITS))
    p.add_argument("--window-tokens", type=int)
    p.add_argument("--weekly-tokens", type=int)
    p.set_defaults(func=cmd_usage)

    p = sub.add_parser("setup", parents=[common], help="create table/ without opening the dashboard")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("list", parents=[common], help="topics on the table")
    p.set_defaults(func=cmd_list)

    args = ap.parse_args(argv)
    if not args.cmd:
        args.port, args.no_browser = 7777, False
        return cmd_dash(args)
    return args.func(args)
