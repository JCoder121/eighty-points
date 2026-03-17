# Shengji (升级)

A multiplayer web-based card game supporting Upgrade (升级) and Find Friends (找朋友) modes.

## Dev commands

```bash
# Install dependencies (editable mode + dev tools)
pip install -e ".[dev]"

# Run tests
pytest

# Run the server (auto-reloads on file changes)
uvicorn shengji.network.app:app --reload

# Lint
ruff check src/ tests/
```

## Rules reference

https://robertying.com/shengji/rules.html
