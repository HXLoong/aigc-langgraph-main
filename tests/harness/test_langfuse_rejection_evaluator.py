"""正确拒绝必须命中特定业务拒绝并证明未提交，不能把异常当作通过。"""
from types import SimpleNamespace

import pytest

from harness.evaluators import rejection_match


def evaluate(expected, output):
    ctx = SimpleNamespace(
        experiment=SimpleNamespace(item_expected_output={'expected': expected}),
        observation=SimpleNamespace(output={'turns': [output]}),
    )
    return rejection_match.evaluate(ctx).scores[0]


def rejected(kind='ambiguous_action'):
    node, error_type = ('swap_extract_candidates', 'AmbiguousActionError') if kind == 'ambiguous_action' else ('swap_normalize', 'NonPositiveQuantityError')
    return {'error': {'node': node, 'type': error_type}, 'api_code': None, 'api_result': None,
            'place_params': None, 'reply_text': '请明确本轮动作', 'trace': f'ingest → {node}[error] → render'}


@pytest.mark.parametrize('kind', ['ambiguous_action', 'non_positive_quantity'])
def test_accepts_only_declared_business_rejection(kind):
    assert evaluate({'rejection': kind}, rejected(kind)).value is True


@pytest.mark.parametrize('change', [
    {'error': {'node': 'swap_extract_candidates', 'type': 'TimeoutError'}},
    {'error': {'node': 'swap_place_order_submit', 'type': 'AmbiguousActionError'}},
    {'api_code': 500}, {'api_result': 'GOATS失败'}, {'place_params': {'orderList': [{}]}},
    {'trace': 'swap_extract_candidates[error] → swap_place_order_submit → render'},
    {'trace': ''}, {'reply_text': ''}, {'error': None},
])
def test_does_not_accept_runtime_failure_or_backend_submission(change):
    output = rejected(); output.update(change)
    assert evaluate({'rejection': 'ambiguous_action'}, output).value is False


def test_unlabeled_rejection_does_not_pass():
    assert evaluate({}, rejected()).value is False
    assert evaluate({'rejection': 'anything'}, rejected()).value is False
