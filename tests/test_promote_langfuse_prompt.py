"""scripts/langfuse/promote_langfuse_prompt.py · F4.6 prompt 晋升测试（ADR 0014 D3）。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.langfuse import promote_langfuse_prompt as ppm

# ============================================================
# _parse_target
# ============================================================


def test_parse_target_simple() -> None:
    assert ppm._parse_target("swap.intent") == ("swap", "intent")


def test_parse_target_with_underscore_in_name() -> None:
    assert ppm._parse_target("option.extract_inquiry") == ("option", "extract_inquiry")


def test_parse_target_with_underscore_in_category() -> None:
    """option_close.confirm_close 这种 multi-word category 也合法。"""
    assert ppm._parse_target("option_close.confirm_close") == (
        "option_close",
        "confirm_close",
    )


def test_parse_target_missing_dot_exits() -> None:
    with pytest.raises(SystemExit) as exc_info:
        ppm._parse_target("swapintent")
    assert exc_info.value.code == 1


# ============================================================
# _next_version
# ============================================================


def test_next_version_existing_v1_only(tmp_path: Path, monkeypatch) -> None:
    """只有 intent.md → 下一个 v 是 2。"""
    monkeypatch.setattr(ppm, "PROMPTS_ROOT", tmp_path)
    (tmp_path / "swap").mkdir()
    (tmp_path / "swap" / "intent.md").write_text("v1 content", encoding="utf-8")
    assert ppm._next_version("swap", "intent") == 2


def test_next_version_existing_v2(tmp_path: Path, monkeypatch) -> None:
    """有 intent_v2.md → 下一个 v 是 3。"""
    monkeypatch.setattr(ppm, "PROMPTS_ROOT", tmp_path)
    (tmp_path / "swap").mkdir()
    (tmp_path / "swap" / "intent.md").write_text("v1", encoding="utf-8")
    (tmp_path / "swap" / "intent_v2.md").write_text("v2", encoding="utf-8")
    assert ppm._next_version("swap", "intent") == 3


def test_next_version_existing_v5_nonconsecutive(tmp_path: Path, monkeypatch) -> None:
    """v2 / v5 跳号 → 下一个用 v6（最大 +1）。"""
    monkeypatch.setattr(ppm, "PROMPTS_ROOT", tmp_path)
    (tmp_path / "swap").mkdir()
    (tmp_path / "swap" / "intent.md").write_text("v1", encoding="utf-8")
    (tmp_path / "swap" / "intent_v2.md").write_text("v2", encoding="utf-8")
    (tmp_path / "swap" / "intent_v5.md").write_text("v5", encoding="utf-8")
    assert ppm._next_version("swap", "intent") == 6


def test_next_version_missing_base_exits(tmp_path: Path, monkeypatch) -> None:
    """base file 不存在拒绝晋升（git 必须先有 v1）。"""
    monkeypatch.setattr(ppm, "PROMPTS_ROOT", tmp_path)
    (tmp_path / "swap").mkdir()
    with pytest.raises(SystemExit) as exc_info:
        ppm._next_version("swap", "nonexistent")
    assert exc_info.value.code == 1


def test_next_version_unknown_category_exits(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ppm, "PROMPTS_ROOT", tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        ppm._next_version("nonexistent_cat", "x")
    assert exc_info.value.code == 1


# ============================================================
# _langfuse_name · 与 app/prompts/__init__.py 同款约定
# ============================================================


def test_langfuse_name_basic() -> None:
    assert ppm._langfuse_name("swap", "intent") == "swap_intent"


def test_langfuse_name_with_slash_category() -> None:
    """category 含 / 时拆开拼接。"""
    assert ppm._langfuse_name("option/close", "place") == "option_close_place"


# ============================================================
# _render_markdown_from_langfuse · LangFuse 内容渲染
# ============================================================


def test_render_string_content() -> None:
    prompt = MagicMock()
    prompt.prompt = "Hello World"
    prompt.version = 3
    from app.prompts import _parse_prompt_md  # type: ignore[attr-defined]

    md, v = ppm._render_markdown_from_langfuse(prompt, "x")
    assert _parse_prompt_md(md)[0] == "Hello World"
    assert v == 3


def test_render_message_list_with_system_and_user() -> None:
    prompt = MagicMock()
    prompt.prompt = [
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "raw: {{raw}}"},
    ]
    prompt.version = 5
    md, v = ppm._render_markdown_from_langfuse(prompt, "x")
    from app.prompts import _parse_prompt_md  # type: ignore[attr-defined]

    system, user = _parse_prompt_md(md)
    assert system == "你是助手"
    assert user == "raw: {{raw}}"
    assert v == 5


def test_render_message_list_system_only() -> None:
    prompt = MagicMock()
    prompt.prompt = [{"role": "system", "content": "only system"}]
    prompt.version = 1
    from app.prompts import _parse_prompt_md  # type: ignore[attr-defined]

    md, _ = ppm._render_markdown_from_langfuse(prompt, "x")
    assert _parse_prompt_md(md) == ("only system", "")


def test_render_empty_system_exits() -> None:
    prompt = MagicMock()
    prompt.prompt = [{"role": "user", "content": "no system"}]
    with pytest.raises(SystemExit) as exc_info:
        ppm._render_markdown_from_langfuse(prompt, "x")
    assert exc_info.value.code == 1


def test_render_empty_string_exits() -> None:
    prompt = MagicMock()
    prompt.prompt = "   "
    with pytest.raises(SystemExit) as exc_info:
        ppm._render_markdown_from_langfuse(prompt, "x")
    assert exc_info.value.code == 1


def test_render_unknown_type_exits() -> None:
    prompt = MagicMock()
    prompt.prompt = 12345  # int 不是合法格式
    with pytest.raises(SystemExit) as exc_info:
        ppm._render_markdown_from_langfuse(prompt, "x")
    assert exc_info.value.code == 1


# ============================================================
# _write_target
# ============================================================


def test_write_target_creates_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ppm, "PROMPTS_ROOT", tmp_path)
    (tmp_path / "swap").mkdir()
    target = ppm._write_target("swap", "intent", 3, "new v3 content")
    assert target.read_text(encoding="utf-8") == "new v3 content"
    assert target.name == "intent_v3.md"


def test_write_target_refuses_overwrite(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ppm, "PROMPTS_ROOT", tmp_path)
    (tmp_path / "swap").mkdir()
    (tmp_path / "swap" / "intent_v3.md").write_text("existing", encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        ppm._write_target("swap", "intent", 3, "new")
    assert exc_info.value.code == 3
    # 原内容不变
    assert (tmp_path / "swap" / "intent_v3.md").read_text(encoding="utf-8") == "existing"


def test_write_target_force_overwrite(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ppm, "PROMPTS_ROOT", tmp_path)
    (tmp_path / "swap").mkdir()
    (tmp_path / "swap" / "intent_v3.md").write_text("existing", encoding="utf-8")
    target = ppm._write_target("swap", "intent", 3, "new", force=True)
    assert target.read_text(encoding="utf-8") == "new"


# ============================================================
# 端到端 mock LangFuse SDK 流程
# ============================================================


def test_e2e_promote_with_mock_langfuse(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """完整流程：mock LangFuse get_prompt → 写文件 → 输出 git commit 提示。"""
    monkeypatch.setattr(ppm, "PROMPTS_ROOT", tmp_path)
    (tmp_path / "swap").mkdir()
    (tmp_path / "swap" / "intent.md").write_text("v1 content", encoding="utf-8")
    (tmp_path / "swap" / "intent_v2.md").write_text("v2 content", encoding="utf-8")

    fake_prompt = MagicMock()
    fake_prompt.prompt = "promoted v3 content from langfuse"
    fake_prompt.version = 7  # LangFuse 内部版本

    fake_lf = MagicMock()
    fake_lf.get_prompt = MagicMock(return_value=fake_prompt)

    with (
        patch.object(ppm, "_fetch_langfuse_prompt", return_value=("promoted v3 content from langfuse\n", 7)),
        patch.object(sys, "argv", ["promote_langfuse_prompt.py", "swap.intent"]),
    ):
        rc = ppm.main()

    assert rc == 0
    target = tmp_path / "swap" / "intent_v3.md"
    assert target.exists()
    assert "promoted v3 content from langfuse" in target.read_text(encoding="utf-8")

    out = capsys.readouterr().out
    assert "晋升成功" in out
    assert "intent_v3.md" in out
    assert "v7" in out  # LangFuse 内部版本号体现在 commit 提示
    assert "git commit" in out


def test_e2e_dry_run_does_not_write(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(ppm, "PROMPTS_ROOT", tmp_path)
    (tmp_path / "swap").mkdir()
    (tmp_path / "swap" / "intent.md").write_text("v1", encoding="utf-8")

    with (
        patch.object(ppm, "_fetch_langfuse_prompt", return_value=("preview content\n", 4)),
        patch.object(sys, "argv", ["promote_langfuse_prompt.py", "swap.intent", "--dry-run"]),
    ):
        rc = ppm.main()

    assert rc == 0
    assert not (tmp_path / "swap" / "intent_v2.md").exists()
    out = capsys.readouterr().out
    assert "[dry-run]" in out
    assert "preview content" in out


def test_e2e_explicit_version_arg(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """--version 5 强制输出 v5.md，跳过 next_version 自动逻辑。"""
    monkeypatch.setattr(ppm, "PROMPTS_ROOT", tmp_path)
    (tmp_path / "swap").mkdir()
    (tmp_path / "swap" / "intent.md").write_text("v1", encoding="utf-8")

    with (
        patch.object(ppm, "_fetch_langfuse_prompt", return_value=("v5 content\n", 9)),
        patch.object(sys, "argv", [
            "promote_langfuse_prompt.py", "swap.intent", "--version", "5"
        ]),
    ):
        rc = ppm.main()

    assert rc == 0
    assert (tmp_path / "swap" / "intent_v5.md").exists()
    assert not (tmp_path / "swap" / "intent_v2.md").exists()
