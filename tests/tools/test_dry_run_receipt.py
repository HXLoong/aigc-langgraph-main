"""干跑适配器必须满足真实回执读取接口，且不能发送 HTTP 或伪造订单号。"""
import httpx
import pytest

from app.tools.option_client import FinancialOrderOpenApiSaveReqVO, OptionClientHttpx
from app.tools.receipts import receipt_update
from app.tools.swap_client import SwapClientHttpx, SwapOrderOpenApiSaveReqVO


@pytest.mark.parametrize('target', ['swap', 'option'])
async def test_dry_run_write_returns_readable_non_transaction_receipt_without_http(target):
    def forbid_http(request):
        pytest.fail('dry-run must not dispatch HTTP')

    kwargs = {'base_url': 'http://local.invalid', 'token': 'test',
              'transport': httpx.MockTransport(forbid_http), 'dry_run': True}
    context = {'roomId': 'r', 'userId': 'u', 'messageId': 1, 'conversationId': 'c',
               'messageContent': '测试', 'rawContent': '测试'}
    if target == 'swap':
        response = await SwapClientHttpx(**kwargs).operate(SwapOrderOpenApiSaveReqVO(
            **context, type='place_order_request', orderList=[],
        ))
    else:
        response = await OptionClientHttpx(**kwargs).operate(FinancialOrderOpenApiSaveReqVO(
            **context, type='place_order_from_quote', orderList=[],
        ))
    update = receipt_update(response, target)
    assert update['api_code'] == 0
    assert 'DRY-RUN' in update['api_result'] and '未发送交易请求' in update['api_result']
    assert 'orderId' not in update['api_result']
