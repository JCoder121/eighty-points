"""Pretty-print a game log file for debugging.

Usage:
    python scripts/replay_log.py logs/games/<room_id>_<timestamp>.jsonl
"""

import json
import sys


def replay(path: str) -> None:
    with open(path) as f:
        for i, line in enumerate(f, 1):
            event = json.loads(line)
            print(f"[{i:04d}] {json.dumps(event, indent=2)}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/replay_log.py <log_file>")
        sys.exit(1)
    replay(sys.argv[1])
