# Contributing

Issues and pull requests are welcome.

## The one real rule

**Standard library only.** No `requirements.txt`, no `pyproject.toml`, no vendored
packages. SyncAgent is one file you can copy anywhere and run, and that property is
most of its value. A dependency defeats the point — if a change needs one, it probably
belongs in your own fork rather than here.

The same goes for structure: keep it in `syncagent.py`. Splitting it into a package
would be tidier and would make it harder to drop into a folder and use.

## Before you open a PR

Target Python 3.8, and keep it working on macOS, Linux, and Windows. Run the tests:

```bash
python -m unittest discover -s tests
```

Then the smoke sequence (use `python3` on macOS and Linux):

```bash
python syncagent.py init /tmp/sa-check --track code --name Check
cd /tmp/sa-check
python syncagent.py status
python syncagent.py gate build     # must exit non-zero: SPEC is DRAFT
python syncagent.py dash --port 7799
```

If you touched `collect_change()`, also check it against a repo with no commits and one
with untracked files — those are the two cases it exists to handle. If you touched the
ordering or disjointness rules, `tests/test_tasks.py` covers them as pure functions; add
a case there rather than testing through a workspace.

Two portability traps worth knowing about, both already handled — please don't
reintroduce them:

- Launch CLIs through `exe()`, never a bare name. On Windows the three CLIs are npm
  shims (`gemini.CMD`), which `shutil.which` finds but `CreateProcess` will not run.
- Generated instructions must use `cli_invocation()`, never a literal
  `python syncagent.py`. The workspace is not the install folder, and macOS has no
  `python` command at all.

## Changing prompts

The prompt templates in `syncagent.py` are behaviour, not documentation. If you change
one, say in the PR what got worse without it. The constraints that look arbitrary
(file:line required, empty findings allowed, two rounds maximum) each replaced a
specific failure, so please don't relax them without a reason.

## Scope

Good fits: bugs, Windows/macOS/Linux portability, better parsing of the two CLIs' JSON
output, dashboard clarity, new tracks.

Poor fits: a plugin system, a config framework, a web UI beyond the local dashboard,
support for a fourth agent that nobody asked for.
