"""Allow `python -m harness <cmd>`."""
from harness.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
