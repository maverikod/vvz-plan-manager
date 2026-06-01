# Plan Manager

**Author:** Vasiliy Zdanovskiy  
**Email:** vasilyvz@gmail.com  
**Project ID:** f06b7269-cc9c-4293-886b-24984e4033ba

Plan Manager is a standalone MCP server that exposes development plans
as a structured tree API. Plans are stored on disk following PLAN_STANDARD.md
and operated through buffer-based commands (load / read / write / flush / undo / diff).

## Quick Start

```bash
cd /home/vasilyvz/projects/tools/plan_manager
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m plan_manager.main --config config.json
```

## Project layout

```
plan_manager/
├── plan_manager/          # Python package
│   ├── __init__.py
│   ├── main.py            # entry point
│   ├── commands/          # MCP commands
│   ├── core/              # buffer, tree, validation
│   └── standards/         # embedded PLAN_STANDARD copy
├── tests/
├── docs/
├── config.json
├── pyproject.toml
└── projectid
```

## Standards

See `code_analysis/docs/standards/PLAN_STANDARD.md` for the plan structure standard.
