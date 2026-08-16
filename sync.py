#!/usr/bin/env python3
"""SyncAgent entry point.

    python sync.py            open the table
    python sync.py ask "..."  put a need on it from the terminal
    python sync.py doctor     check that each seat can actually answer

Equivalent to `python -m syncagent`. Standard library only - nothing to install.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from syncagent.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
