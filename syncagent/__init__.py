"""SyncAgent - a table your AI agents sit around.

A need goes on the table. One seat picks it up, leaves a markdown file, and says
who should take it next. One seat runs at a time, ever.

    python sync.py

Layout:
    table.py    the folder model: topics, briefs, handoffs, depth slicing
    seats.py    the three CLI adapters
    runner.py   the single-worker relay
    usage.py    measured Claude spend
    server.py   dashboard HTTP + API
    ui.py       the page
"""

__version__ = "2.0"

from .table import (  # noqa: F401
    DEFAULT_DEPTH, DEFAULT_LENS, DEPTHS, LENSES, create_topic, find_table,
    load_config, parse_handoff, prior_turns, section, seat_order,
)
from .usage import (  # noqa: F401
    DEFAULT_LIMITS, IDLE_SECONDS, LIVE_SECONDS, PLAN_LIMITS, TOKEN_WEIGHTS,
    agent_state, claude_usage_report, project_slug, read_claude_usage,
    resolve_limits,
)
from .util import TABLE  # noqa: F401
