"""`python -m harness.case_generator <cmd>` 入口。"""
from __future__ import annotations

import sys

from harness.case_generator.cli import main

if __name__ == "__main__":
    sys.exit(main())
