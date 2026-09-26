"""Compatibility entry point for the v2 modular application."""
import sys
from aicu.cli import main

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Stopped; saved records.jsonl can be reused.", file=sys.stderr)
        raise SystemExit(130)
