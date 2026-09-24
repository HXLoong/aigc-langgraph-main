"""Git 提示词到 Langfuse staging 的批量同步。"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from langfuse.api.commons.errors.not_found_error import NotFoundError

from scripts.langfuse import upload_prompt_to_langfuse as upload


def _write_prompt(root, category: str, name: str, system: str, user: str | None = None) -> None:
    directory = root / category
    directory.mkdir(parents=True, exist_ok=True)
    content = f"# Title\n\n## [system]\n```\n{system}\n```\n"
    if user is not None:
        content += f"\n## [user]\n```\n{user}\n```\n"
    (directory / f"{name}.md").write_text(content, encoding="utf-8")


class FakeLangfuse:
    def __init__(self, prompts: dict[str, SimpleNamespace] | None = None) -> None:
        self.prompts = prompts or {}
        self.get_calls: list[tuple[str, str, int]] = []
        self.created: list[dict] = []

    def get_prompt(self, name: str, *, label: str, cache_ttl_seconds: int):
        self.get_calls.append((name, label, cache_ttl_seconds))
        if name not in self.prompts:
            raise NotFoundError(body={"message": "not found"})
        return self.prompts[name]

    def create_prompt(self, **kwargs):
        self.created.append(kwargs)
        self.prompts[kwargs["name"]] = SimpleNamespace(
            type=kwargs["type"], prompt=kwargs["prompt"], version=len(self.created)
        )
        return self.prompts[kwargs["name"]]


def test_collect_scans_only_top_level_prompt_files_and_maps_content(tmp_path) -> None:
    _write_prompt(tmp_path, "option", "intent", "system original")
    _write_prompt(tmp_path, "option_close", "intent_v2", "close", "user {{var}}")
    _write_prompt(tmp_path, "swap", "intent", "swap")
    _write_prompt(tmp_path / "swap", "nested", "ignored", "nested")
    (tmp_path / "swap" / "notes.txt").write_text("ignored", encoding="utf-8")

    prompts = upload._collect_sync_prompts(tmp_path)

    assert [prompt.name for prompt in prompts] == [
        "option_intent",
        "option_close_intent_v2",
        "swap_intent",
    ]
    assert prompts[0].body == [
        {"role": "system", "content": "system original"},
        {"role": "user", "content": upload.EXPERIMENT_USER_TEMPLATE},
    ]
    assert prompts[1].body == [
        {"role": "system", "content": "close"},
        {"role": "user", "content": "user {{var}}"},
    ]


def test_sync_prevalidates_all_files_before_any_remote_write(tmp_path) -> None:
    _write_prompt(tmp_path, "option", "intent", "valid")
    _write_prompt(tmp_path, "swap", "broken", "")
    client = FakeLangfuse()

    with pytest.raises(ValueError, match="broken.md"):
        upload._sync_all(client, tmp_path)

    assert client.get_calls == []
    assert client.created == []


def test_sync_rejects_unparseable_user_section_before_any_write(tmp_path) -> None:
    _write_prompt(tmp_path, "option", "intent", "valid")
    directory = tmp_path / "swap"
    directory.mkdir()
    (directory / "broken.md").write_text(
        "## [system]\n```\nsystem\n```\n\n## [user]\n```\nunfinished",
        encoding="utf-8",
    )
    client = FakeLangfuse()

    with pytest.raises(ValueError, match="broken.md"):
        upload._sync_all(client, tmp_path)
    assert client.get_calls == []
    assert client.created == []


def test_sync_rejects_name_collision_before_any_remote_write(tmp_path, monkeypatch) -> None:
    _write_prompt(tmp_path, "option", "intent", "one")
    _write_prompt(tmp_path, "swap", "intent", "two")
    monkeypatch.setattr(upload, "_langfuse_name", lambda _category, _name: "same")
    client = FakeLangfuse()

    with pytest.raises(ValueError, match="same"):
        upload._sync_all(client, tmp_path)

    assert client.get_calls == []
    assert client.created == []


def test_sync_creates_first_version_and_second_run_skips(tmp_path) -> None:
    _write_prompt(tmp_path, "option", "intent", "original")
    client = FakeLangfuse()

    assert upload._sync_all(client, tmp_path) == {"created": 1, "updated": 0, "skipped": 0}
    assert client.created == [
        {
            "name": "option_intent",
            "type": "chat",
            "prompt": [
                {"role": "system", "content": "original"},
                {"role": "user", "content": upload.EXPERIMENT_USER_TEMPLATE},
            ],
            "labels": ["staging"],
        }
    ]
    assert upload._sync_all(client, tmp_path) == {"created": 0, "updated": 0, "skipped": 1}
    assert len(client.created) == 1
    assert client.get_calls == [
        ("option_intent", "staging", 0),
        ("option_intent", "latest", 0),
        ("option_intent", "staging", 0),
    ]


def test_sync_skips_actual_sdk_chat_message_shape(tmp_path) -> None:
    _write_prompt(tmp_path, "option", "intent", "original")
    client = FakeLangfuse(
        {
            "option_intent": SimpleNamespace(
                prompt=[
                    {"type": "message", "role": "system", "content": "original"},
                    {"type": "message", "role": "user", "content": upload.EXPERIMENT_USER_TEMPLATE},
                ],
                version=4,
            )
        }
    )

    assert upload._sync_all(client, tmp_path) == {"created": 0, "updated": 0, "skipped": 1}
    assert client.created == []


def test_sync_overwrites_different_ui_staging_draft_with_git_version(tmp_path) -> None:
    _write_prompt(tmp_path, "swap", "intent", "git content")
    client = FakeLangfuse(
        {
            "swap_intent": SimpleNamespace(
                type="chat", prompt=[{"role": "system", "content": "UI draft"}], version=3
            )
        }
    )

    assert upload._sync_all(client, tmp_path) == {"created": 0, "updated": 1, "skipped": 0}
    assert client.created[0]["prompt"][0]["content"] == "git content"
    assert client.created[0]["labels"] == ["staging"]


def test_sync_rejects_existing_text_prompt_and_auth_error(tmp_path) -> None:
    _write_prompt(tmp_path, "swap", "intent", "git")
    client = FakeLangfuse({"swap_intent": SimpleNamespace(type="text", prompt="old")})
    with pytest.raises(ValueError, match="type"):
        upload._sync_all(client, tmp_path)
    assert client.created == []


def test_sync_rejects_text_prompt_without_staging_label(tmp_path) -> None:
    _write_prompt(tmp_path, "swap", "intent", "git")
    client = FakeLangfuse()

    def get_prompt(name, *, label, cache_ttl_seconds):
        client.get_calls.append((name, label, cache_ttl_seconds))
        if label == "staging":
            raise NotFoundError(body={"message": "not found"})
        return SimpleNamespace(type="text", prompt="old")

    client.get_prompt = get_prompt
    with pytest.raises(ValueError, match="type"):
        upload._sync_all(client, tmp_path)
    assert client.created == []

    client.get_prompt = lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("401"))
    with pytest.raises(PermissionError, match="401"):
        upload._sync_all(client, tmp_path)
    assert client.created == []


def test_sync_aborts_on_network_error_without_treating_it_as_missing(tmp_path) -> None:
    _write_prompt(tmp_path, "swap", "intent", "git")
    client = FakeLangfuse()
    client.get_prompt = lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("down"))

    with pytest.raises(ConnectionError, match="down"):
        upload._sync_all(client, tmp_path)
    assert client.created == []


def test_sync_aborts_when_create_fails(tmp_path) -> None:
    _write_prompt(tmp_path, "swap", "intent", "git")
    client = FakeLangfuse()
    client.create_prompt = lambda **_kwargs: (_ for _ in ()).throw(PermissionError("401"))

    with pytest.raises(PermissionError, match="401"):
        upload._sync_all(client, tmp_path)


def test_cli_sync_all_uses_base_url_and_requires_configuration(
    tmp_path, monkeypatch, capsys
) -> None:
    _write_prompt(tmp_path, "option", "intent", "git")
    monkeypatch.setattr(upload, "PROMPTS_ROOT", tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["upload_prompt_to_langfuse.py", "--sync-all", "--base-url", "https://example.test"],
    )
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert upload.main() == 2
    assert "LANGFUSE_PUBLIC_KEY" in capsys.readouterr().err

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret-test")
    client = FakeLangfuse()
    captured = []
    monkeypatch.setattr(upload, "_new_client", lambda base_url: captured.append(base_url) or client)
    assert upload.main() == 0
    assert captured == ["https://example.test"]
    assert client.created[0]["labels"] == ["staging"]


def test_cli_sync_all_rejects_plain_and_non_staging_label(monkeypatch) -> None:
    for option in ("--plain", "--label=production"):
        monkeypatch.setattr(sys, "argv", ["upload_prompt_to_langfuse.py", "--sync-all", option])
        with pytest.raises(SystemExit, match="2"):
            upload.main()


def test_cli_manual_upload_keeps_sdk_default_url(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["upload_prompt_to_langfuse.py", "option.intent"])
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret-test")
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    captured = []
    client = FakeLangfuse()
    monkeypatch.setattr(upload, "_new_client", lambda base_url: captured.append(base_url) or client)

    assert upload.main() == 0
    assert captured == [None]
    assert client.created[0]["name"] == "option_intent"


def test_cli_manual_upload_plain_pushes_text_prompt(monkeypatch) -> None:
    """--plain：不补实验用 user 消息，按纯 system 的 text 提示词推送。"""
    monkeypatch.setattr(sys, "argv", ["upload_prompt_to_langfuse.py", "option.intent", "--plain"])
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret-test")
    client = FakeLangfuse()
    monkeypatch.setattr(upload, "_new_client", lambda base_url: client)

    assert upload.main() == 0
    created = client.created[0]
    assert created["type"] == "text"
    assert isinstance(created["prompt"], str) and created["prompt"].strip()
    assert created["labels"] == ["staging"]
