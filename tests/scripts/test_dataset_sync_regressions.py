"""Dataset sync must prepare current fixtures and honor the selected target."""
from __future__ import annotations

import importlib
import inspect
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest


def uploader() -> ModuleType:
    return importlib.import_module('scripts.langfuse.upload_golden_to_langfuse')


def test_current_fixtures_can_be_prepared_without_remote_access() -> None:
    module = uploader()
    files = module.prepare_sync_files()
    assert len(files) == 10
    assert sum(len(source.items) for source in files) == 782
    assert len({item['id'] for source in files for item in source.items}) == sum(
        len(source.items) for source in files
    )


def test_sync_discovers_nested_jsonl_and_uses_relative_path_names(tmp_path: Path) -> None:
    sources = {
        'biz/option_close.jsonl': 'case-biz',
        'intent/option_close.jsonl': 'case-intent',
        'biz/nested/swap_prod.jsonl': 'case-nested',
    }
    for relative, case_id in sources.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'id': case_id, 'send_text': '查订单'}) + '\n')
    (tmp_path / 'biz' / 'ignored.csv').write_text('ignored')

    files = uploader().prepare_sync_files(tmp_path)

    assert {source.dataset_name for source in files} == {
        'biz/option_close', 'intent/option_close', 'biz/nested/swap_prod',
    }
    for source in files:
        case_id = sources[source.path.relative_to(tmp_path).as_posix()]
        assert source.items[0]['id'] == f'{source.dataset_name}:{case_id}'
        assert source.items[0]['metadata']['fixture_path'] == (
            source.path.relative_to(tmp_path).as_posix()
        )


def test_duplicate_case_in_one_dataset_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / 'intent' / 'option.jsonl'
    source.parent.mkdir()
    row = json.dumps({'id': 'duplicate', 'send_text': '查订单'})
    source.write_text(row + '\n' + row + '\n')
    with pytest.raises(ValueError, match='Duplicate case ID'):
        uploader().prepare_sync_files(tmp_path)


def test_clear_dataset_requires_explicit_base_url() -> None:
    """缺 base URL 时不能静默落到公网 Langfuse Cloud 等默认地址去删数据。"""
    parameter = inspect.signature(uploader()._clear_dataset).parameters['base_url']
    assert parameter.default is inspect.Parameter.empty


def test_clear_dataset_reuses_one_connection_and_pages_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, dict(request.url.params)))
        if request.method == 'GET':
            page = int(request.url.params['page'])
            size = 100 if page == 1 else 2
            return httpx.Response(200, json={'data': [{'id': f'{page}-{i}'} for i in range(size)]})
        return httpx.Response(200, json={'message': 'deleted'})

    created: list[httpx.Client] = []
    original = httpx.Client

    def client_factory(**kwargs: Any) -> httpx.Client:
        client = original(transport=httpx.MockTransport(handler), **kwargs)
        created.append(client)
        return client

    monkeypatch.setattr(httpx, 'Client', client_factory)
    monkeypatch.setenv('LANGFUSE_PUBLIC_KEY', 'pk')
    monkeypatch.setenv('LANGFUSE_SECRET_KEY', 'sk')
    uploader()._clear_dataset('test', base_url='http://localhost:9999/')

    assert len(created) == 1
    lists = [call for call in calls if call[0] == 'GET']
    assert [call[1] for call in lists] == ['/api/public/dataset-items'] * 2
    assert lists[0][2]['datasetName'] == 'test'
    deletes = [call[1] for call in calls if call[0] == 'DELETE']
    assert len(deletes) == 102
    assert deletes[0] == '/api/public/dataset-items/1-0'


def test_uploaders_share_public_api_dotenv_loader() -> None:
    """.env 解析只有一份（_public_api.load_dotenv 会剥掉行内 # 注释）。"""
    from scripts.langfuse import _public_api

    assert uploader().load_dotenv is _public_api.load_dotenv


@pytest.mark.parametrize(
    ('override', 'env', 'expected'),
    [
        ('http://cli:3000', {'LANGFUSE_BASE_URL': 'http://env:3000'}, 'http://cli:3000'),
        (None, {'LANGFUSE_BASE_URL': 'http://env:3000', 'LANGFUSE_HOST': 'http://h'}, 'http://env:3000'),
        (None, {'LANGFUSE_HOST': 'http://host:3000'}, 'http://host:3000'),
        (None, {}, None),
    ],
)
def test_resolve_base_url_precedence(
    monkeypatch: pytest.MonkeyPatch,
    override: str | None,
    env: dict[str, str],
    expected: str | None,
) -> None:
    from scripts.langfuse._public_api import resolve_base_url

    for key in ('LANGFUSE_BASE_URL', 'LANGFUSE_HOST'):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert resolve_base_url(override) == expected


def test_missing_config_lists_every_absent_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.langfuse._public_api import missing_langfuse_config

    monkeypatch.delenv('LANGFUSE_PUBLIC_KEY', raising=False)
    monkeypatch.setenv('LANGFUSE_SECRET_KEY', 'sk')
    assert missing_langfuse_config(None, require_base_url=True) == [
        'LANGFUSE_BASE_URL (or --base-url)', 'LANGFUSE_PUBLIC_KEY',
    ]
    assert missing_langfuse_config(None, require_base_url=False) == ['LANGFUSE_PUBLIC_KEY']


def test_manual_upload_uses_resolved_dataset_and_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = uploader()
    source = tmp_path / 'cases.jsonl'
    source.write_text(json.dumps({'id': 'one', 'send_text': '查订单'}) + '\n')
    factory = MagicMock()
    monkeypatch.setattr('langfuse.Langfuse', factory)
    monkeypatch.setenv('LANGFUSE_PUBLIC_KEY', 'test')
    monkeypatch.setenv('LANGFUSE_SECRET_KEY', 'test')
    monkeypatch.setattr(sys, 'argv', ['upload', '--source', str(source), '--mode', 'append',
                                     '--base-url', 'http://localhost:9999'])
    assert module.main() == 0
    factory.assert_called_once_with(base_url='http://localhost:9999')
    client = factory.return_value
    assert client.create_dataset.call_args.kwargs['name'] == module.DATASET_NAME
    assert client.create_dataset_item.call_args.kwargs['dataset_name'] == module.DATASET_NAME
