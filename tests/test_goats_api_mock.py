"""GOATS 持仓 mock 的离线 HTTP 契约测试；合成记录仅用于筛选边界。"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

ENDPOINT = "/api/internal/agent/option/position"
HEADERS = {"agentid": "test-room@tl"}


@pytest.fixture
def snapshot() -> dict[str, Any]:
    return {
        "errMsg": "",
        "errCode": {"code": 200, "chs": "成功", "eng": "SUCCESS"},
        "data": {
            "pageNum": 1,
            "pageSize": 4,
            "total": 4,
            "queryResults": [
                {
                    "keyInstrumentId": 101,
                    "windcode": "000155.SZ",
                    "windname": "川能动力",
                    "insFamily": "EQUITY",
                    "contractType": "EUROPEAN_VANILLA",
                    "contractSubType": None,
                    "allowCloseOut": True,
                    "notional": 12345678.125,
                    "trdOtcContrFiles": {"internalTradeId": "synthetic-1"},
                    "strikes": [{"seq": 1, "strikePct": 1.03}],
                    "extraField": {"keep": [None, False, 123]},
                },
                {
                    "keyInstrumentId": 102,
                    "windcode": "000155.SZ",
                    "insFamily": "EQUITY",
                    "contractType": "AUTOCALL",
                    "contractSubType": "SNOWBALLX",
                    "allowCloseOut": False,
                },
                {
                    "keyInstrumentId": 103,
                    "windcode": "000300.SH",
                    "insFamily": "INDEX",
                    "contractType": "AUTOCALL",
                    "contractSubType": "SNOWBALLX",
                    "allowCloseOut": True,
                },
                {
                    "keyInstrumentId": 104,
                    "windcode": "000155.SZ",
                    "insFamily": "EQUITY",
                    "contractType": "EUROPEAN_VANILLA",
                    "contractSubType": "PUTCAP",
                    "allowCloseOut": False,
                },
            ],
        },
    }


@pytest.fixture
def data_file(tmp_path: Path, snapshot: dict[str, Any]) -> Path:
    path = tmp_path / "option_positions.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    return path


def test_returns_complete_snapshot_in_original_order(
    data_file: Path, snapshot: dict[str, Any]
) -> None:
    from scripts.goats_api_mock.server import create_app

    with TestClient(create_app(data_file)) as client:
        response = client.post(
            ENDPOINT, headers=HEADERS, json={"filter": {}, "pageNum": 1, "pageSize": 0}
        )
    assert response.status_code == 200
    assert response.json() == snapshot


@pytest.fixture
def client(data_file: Path) -> Iterator[TestClient]:
    from scripts.goats_api_mock.server import create_app

    with TestClient(create_app(data_file)) as test_client:
        yield test_client


@pytest.mark.parametrize(
    ("filters", "expected_ids"),
    [
        ({"windCode": "000155.SZ"}, [101, 102, 104]),
        ({"contractTypeList": ["EUROPEAN_VANILLA"]}, [101, 104]),
        ({"insFamilyList": ["INDEX"]}, [103]),
        ({"contractSubTypeList": ["SNOWBALLX"]}, [102, 103]),
        ({"contractSubTypeList": ["SNOWBALLX", "PUTCAP"]}, [102, 103, 104]),
        ({"insFamilyList": ["EQUITY", "INDEX"]}, [101, 102, 103, 104]),
        (
            {
                "windCode": "000155.SZ",
                "insFamilyList": ["EQUITY"],
                "contractTypeList": ["EUROPEAN_VANILLA"],
                "contractSubTypeList": ["PUTCAP"],
                "allowCloseOut": "false",
            },
            [104],
        ),
        ({"windCode": "000155.SZ", "insFamilyList": ["INDEX"]}, []),
        ({"windCode": "DOES_NOT_EXIST"}, []),
        ({"contractTypeList": ["DOES_NOT_EXIST"]}, []),
        (
            {
                "windCode": "",
                "insFamilyList": [],
                "contractTypeList": None,
                "contractSubTypeList": [],
                "allowCloseOut": "",
            },
            [101, 102, 103, 104],
        ),
    ],
)
def test_filters_intersect_and_update_total(
    client: TestClient, snapshot: dict[str, Any], filters: dict[str, Any], expected_ids: list[int]
) -> None:
    response = client.post(
        ENDPOINT, headers=HEADERS, json={"filter": filters, "pageNum": 1, "pageSize": 0}
    )
    assert response.status_code == 200
    result = response.json()
    assert result["errCode"] == snapshot["errCode"]
    assert result["errMsg"] == snapshot["errMsg"]
    assert result["data"] == {
        "pageNum": 1,
        "pageSize": len(expected_ids),
        "total": len(expected_ids),
        "queryResults": [
            row
            for row in snapshot["data"]["queryResults"]
            if row["keyInstrumentId"] in expected_ids
        ],
    }


@pytest.mark.parametrize("value", [True, "true", "TRUE"])
def test_true_only_returns_closeable_positions(client: TestClient, value: bool | str) -> None:
    result = client.post(ENDPOINT, headers=HEADERS, json={"filter": {"allowCloseOut": value}})
    assert result.status_code == 200
    assert [row["keyInstrumentId"] for row in result.json()["data"]["queryResults"]] == [101, 103]


@pytest.mark.parametrize("value", [False, "false", "FALSE", None, ""])
def test_false_or_empty_does_not_filter_positions(
    client: TestClient, value: bool | str | None
) -> None:
    result = client.post(ENDPOINT, headers=HEADERS, json={"filter": {"allowCloseOut": value}})
    assert result.status_code == 200
    assert result.json()["data"]["total"] == 4


def test_all_identities_share_repeatable_data(client: TestClient, snapshot: dict[str, Any]) -> None:
    for headers in (HEADERS, {"agentid": "other-room@tl", "agentsubid": "other-user"}, HEADERS):
        assert client.post(ENDPOINT, headers=headers, json={}).json() == snapshot
        client.post(ENDPOINT, headers=headers, json={"filter": {"windCode": "DOES_NOT_EXIST"}})


def test_group_header_is_required(client: TestClient) -> None:
    assert client.post(ENDPOINT, json={}).status_code == 422


def test_null_filter_is_unrestricted(client: TestClient, snapshot: dict[str, Any]) -> None:
    assert client.post(ENDPOINT, headers=HEADERS, json={"filter": None}).json() == snapshot


def test_loads_data_at_startup_and_changes_require_restart(
    data_file: Path, snapshot: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    from scripts.goats_api_mock.server import create_app

    caplog.set_level(logging.INFO, logger="scripts.goats_api_mock.server")
    app = create_app(data_file)
    snapshot["data"]["queryResults"] = snapshot["data"]["queryResults"][:1]
    snapshot["data"]["total"] = 1
    snapshot["data"]["pageSize"] = 1
    data_file.write_text(json.dumps(snapshot), encoding="utf-8")
    with TestClient(app) as running:
        assert f"持仓数据加载完成：文件={data_file}，数量=1 条" in caplog.text
        assert running.post(ENDPOINT, headers=HEADERS, json={}).json() == snapshot
        data_file.write_text("invalid JSON after startup", encoding="utf-8")
        assert running.post(ENDPOINT, headers=HEADERS, json={}).json() == snapshot
    with (
        pytest.raises(ValueError, match="option_positions.json"),
        TestClient(create_app(data_file)),
    ):
        pass


@pytest.mark.parametrize(
    "content",
    ["not json", "[]", "{}", '{"data": {"queryResults": []}}'],
)
def test_invalid_snapshot_fails_startup(tmp_path: Path, content: str) -> None:
    from scripts.goats_api_mock.server import create_app

    path = tmp_path / "option_positions.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="option_positions.json"), TestClient(create_app(path)):
        pass


@pytest.mark.parametrize("bad_rows", [None, {}, [1], [{}]])
def test_invalid_records_fail_startup(
    data_file: Path, snapshot: dict[str, Any], bad_rows: Any
) -> None:
    from scripts.goats_api_mock.server import create_app

    snapshot["data"]["queryResults"] = bad_rows
    data_file.write_text(json.dumps(snapshot), encoding="utf-8")
    with (
        pytest.raises(ValueError, match="option_positions.json"),
        TestClient(create_app(data_file)),
    ):
        pass


def test_missing_file_fails_startup(tmp_path: Path) -> None:
    from scripts.goats_api_mock.server import create_app

    with (
        pytest.raises(ValueError, match="option_positions.json"),
        TestClient(create_app(tmp_path / "option_positions.json")),
    ):
        pass


@pytest.mark.parametrize(
    ("filters", "expected_ids"),
    [
        (
            {},
            [
                5252598,
                5361523,
                5361527,
                5264220,
                5259836,
                5259772,
                5252540,
                5252513,
                5259759,
                5394291,
                5380178,
                5259784,
                9000000001,
            ],
        ),
        ({"windCode": "000155.SZ"}, [5252598, 5252540, 5252513, 9000000001]),
        ({"contractTypeList": ["EUROPEAN_VANILLA"]}, [5252598, 5252540, 5252513, 9000000001]),
        (
            {
                "contractTypeList": ["AUTOCALL"],
                "contractSubTypeList": ["NONCONSTANT"],
                "insFamilyList": ["EQUITY"],
                "allowCloseOut": "true",
            },
            [5259836, 5394291, 5380178, 5259784],
        ),
    ],
)
def test_supplied_positions(filters: dict[str, Any], expected_ids: list[int]) -> None:
    from scripts.goats_api_mock.server import DEFAULT_DATA_FILE, create_app

    original = json.loads(DEFAULT_DATA_FILE.read_text(encoding="utf-8"))
    assert original["data"]["total"] == len(original["data"]["queryResults"]) == 13
    # Java 按合约编号排序：case-033 引用第二笔，case-032 引用第三笔全平 100 万。
    ordered = sorted(original["data"]["queryResults"], key=lambda row: row["contractCode"])
    assert [row["contractCode"] for row in ordered[:3]] == [
        "OPT-AAAA1", "OPT-LYAFT20260001", "OPT-SZZSCF20260001",
    ]
    assert ordered[2]["availableNotional"] == ordered[2]["notional"] == 1_000_000
    with TestClient(create_app()) as client:
        response = client.post(
            ENDPOINT, headers=HEADERS, json={"filter": filters, "pageNum": 1, "pageSize": 0}
        )
    assert response.status_code == 200
    result = response.json()
    assert result["errCode"] == {"code": 200, "chs": "请求成功", "eng": "SUCCESS_REQUEST"}
    assert result["errMsg"] is None
    assert result["data"]["total"] == result["data"]["pageSize"] == len(expected_ids)
    assert [row["keyInstrumentId"] for row in result["data"]["queryResults"]] == expected_ids
    assert result["data"]["queryResults"] == [
        row for row in original["data"]["queryResults"] if row["keyInstrumentId"] in expected_ids
    ]


def test_positive_page_size_pages_matching_results(client: TestClient) -> None:
    response = client.post(
        ENDPOINT,
        headers=HEADERS,
        json={"filter": {"windCode": "000155.SZ"}, "pageNum": 2, "pageSize": 2},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 3
    assert data["pageNum"] == 2
    assert data["pageSize"] == 1
    assert [row["keyInstrumentId"] for row in data["queryResults"]] == [104]
