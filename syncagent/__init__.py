"""SyncAgent - a table your AI agents sit around.

A need goes on the table. One seat picks it up, leaves a markdown file, and says
who should take it next. One seat runs at a time, ever.

    python sync.py

Layout:
    table.py    the folder model: topics, briefs, handoffs, depth slicing
    seats.py    the three CLI adapters
    runner.py   the single-worker relay
    usage.py    what Claude says is left, asked of Claude
    server.py   dashboard HTTP + API
    ui.py       the page
"""

__version__ = "2.1"

from .table import (  # noqa: F401
    DEFAULT_DEPTH, DEFAULT_LENS, DEPTHS, LENSES, create_topic, find_table,
    load_config, parse_handoff, prior_turns, section, seat_order,
)
from .usage import (  # noqa: F401
    IDLE_SECONDS, LIVE_SECONDS, REFRESH_SECONDS, UsageMeter, agent_state,
    ask_claude, parse_usage,
)
from .util import TABLE  # noqa: F401
