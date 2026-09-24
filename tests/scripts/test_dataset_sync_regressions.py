"""Dataset sync must prepare current fixtures and honor the selected target."""
from __future__ import annotations

import importlib
import json
import sys
from unittest.mock import MagicMock

import pytest


def uploader():
    return importlib.import_module('scripts.langfuse.upload_golden_to_langfuse')


def test_current_fixtures_can_be_prepared_without_remote_access():
    module = uploader()
    files = module.prepare_sync_files()
    assert files
    assert sum(len(source.items) for source in files) > 700
    assert len({item['id'] for source in files for item in source.items}) == sum(
        len(source.items) for source in files
    )


def test_duplicate_case_in_one_dataset_is_rejected(tmp_path):
    source = tmp_path / 'intent' / 'option.jsonl'
    source.parent.mkdir()
    row = json.dumps({'id': 'duplicate', 'send_text': '查订单'})
    source.write_text(row + '\n' + row + '\n')
    with pytest.raises(ValueError, match='Duplicate case ID'):
        uploader().prepare_sync_files(tmp_path)


def test_clear_dataset_uses_explicit_base_url(monkeypatch):
    module = uploader()
    response = MagicMock(status_code=200)
    response.json.return_value = {'data': []}
    get = MagicMock(return_value=response)
    monkeypatch.setattr('httpx.get', get)
    module._clear_dataset('test', base_url='http://localhost:9999/')
    assert get.call_args.args == ('http://localhost:9999/api/public/dataset-items',)


def test_manual_upload_uses_resolved_dataset_and_host(tmp_path, monkeypatch):
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
