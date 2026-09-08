#!/usr/bin/env python3
"""Reuse the validated YAML-to-JSONL converter used by the Dify regression suite."""

from __future__ import annotations

import sys
from pathlib import Path

DIFY_HELPER_DIR = Path(__file__).resolve().parent.parent / "ai_test_dify"
if str(DIFY_HELPER_DIR) not in sys.path:
    sys.path.insert(0, str(DIFY_HELPER_DIR))

from yaml_to_jsonl import main

if __name__ == "__main__":
    raise SystemExit(main())
