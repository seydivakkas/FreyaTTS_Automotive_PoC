# M08 Harness Decisions (20261126T004342Z)
- Reuse existing pytest 9.2.0 and `.venv/Scripts/python.exe` without adding dependencies.
- All `tests/harness/` imports are passive (no CUDA, torch, faster_whisper, backend.main, or backend.db at import time).
- Static AST and passive catalog introspection used for API/UI/DB/Config compatibility without triggering production side effects.
