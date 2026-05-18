"""全局 pytest 配置（占位）。

根 CLAUDE.md「绝对禁止」明确：不在 conftest.py 用 autouse fixture 全局
绕过真实业务路径。需要 mock 时在各自测试文件里通过 monkeypatch / 显式 fixture
按"patch where it's looked up"完成（见 .claude/rules/testing.md）。
"""
from __future__ import annotations
