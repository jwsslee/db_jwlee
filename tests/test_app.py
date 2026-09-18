"""네트워크·키 없이 검증하는 응답 처리, 재무 계산, Streamlit 통합 테스트."""
import importlib.util
import io
import json
import sys
import zipfile
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import requests
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app


def test_missing_values_and_zero_are_distinct():
    assert app.number("-") is None
    assert app.number("0") == 0
    assert app.number("(1,234)") == -1234
    assert app.ratio(10, 0) is None
    assert app.ratio(10, -2) is None


def test_krx_auth_error_and_wrong_date_are_not_empty_data():
    with pytest.raises(app.APIError, match="401"):
        app.parse_krx({"respCode": "401", "respMsg": "Unauthorized Key"}, "20260917")
    with pytest.raises(app.APIError, match="DATE"):
        app.parse_krx({"OutBlock_1": [{"BAS_DD": "20200414"}]}, "20260917")
    assert app.parse_krx({"OutBlock_1": []}, "20260917") == []
    with pytest.raises(app.APIError, match="FORMAT"):
        app.parse_krx({}, "20260917")


@pytest.mark.parametrize("code", ["010", "011", "012", "020", "800", "901"])
def test_dart_errors_preserve_meaning(code):
    with pytest.raises(app.APIError) as error:
        app.dart_status({"status": code})
    assert error.value.code == code
    assert app.dart_status({"status": "013"}) is False


def zipped_corporation():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("CORPCODE.xml", '<result><list><corp_code>00126380</corp_code><corp_name>테스트회사</corp_name><stock_code>005930</stock_code><modify_date>20260101</modify_date></list></result>')
    return stream.getvalue()


def test_dart_corporation_zip_preserves_leading_zeroes():
    mapping = app.parse_corporations(zipped_corporation())
    assert mapping["005930"]["corp"] == "00126380"
    with pytest.raises(app.APIError, match="012"):
        app.parse_corporations(b'<result><status>012</status></result>')


def account_row(kind, amount, cumulative=None):
    identifiers, _, sections = app.ACCOUNTS[kind]
    return dict(account_id=identifiers[0], account_nm=kind, sj_div=sorted(sections)[0],
                thstrm_amount=str(amount), thstrm_add_amount=str(cumulative) if cumulative is not None else "",
                currency="KRW", rcept_no="20260318000001")


def financial_reports():
    result = {}
    for year in (2023, 2024, 2025):
        for quarter in (1, 2, 3, 4):
            quarterly = {"revenue": 100, "operating": 20, "profit": 12,
                         "owner_profit": 10, "eps": 2}
            rows = [account_row(k, v * 4 if quarter == 4 else v, v * quarter)
                    for k, v in quarterly.items()]
            rows += [account_row("equity", 300), account_row("owner_equity", 200),
                     account_row("liabilities", 150), account_row("ocf", 30 * quarter)]
            result[app.period_number(year, quarter)] = rows
    return result


def test_q4_is_annual_minus_nine_months_and_ttm_not_annualized_again():
    reports = financial_reports()
    latest = app.period_number(2025, 4)
    assert app.quarter_amount(reports, latest, "revenue") == 100
    _, metrics = app.financial_metrics(reports, latest, "CFS", 80, 300)
    assert metrics["ttm_eps"] == 8
    assert metrics["per"] == 10
    assert metrics["roe"] == 20  # 40 / mean(200, 200)
    assert metrics["debt"] == 50
    assert metrics["ocf"] == 120  # CF stays YTD, not last quarter
    assert metrics["revenue_growth"] == 0


def test_missing_quarter_does_not_create_per_or_roe():
    reports = financial_reports()
    latest = app.period_number(2025, 4)
    reports[latest - 1] = []
    _, metrics = app.financial_metrics(reports, latest, "CFS", 80, 300)
    assert metrics["per"] is None
    assert metrics["roe"] is None
    assert app.quarter_amount(reports, latest, "revenue") is None


def test_negative_eps_does_not_produce_positive_per():
    reports = financial_reports()
    for rows in reports.values():
        for row in rows:
            if row["account_id"] == app.ACCOUNTS["eps"][0][0]:
                row["thstrm_amount"] = "-" + row["thstrm_amount"]
                row["thstrm_add_amount"] = "-" + row["thstrm_add_amount"]
    _, metrics = app.financial_metrics(reports, app.period_number(2025, 4), "CFS", 80, 300)
    assert metrics["per"] is None


def test_dividend_uses_common_share_per_share_cash_amount():
    assert app.extract_dividend([
        dict(se="주당 현금배당금(원)", stock_knd="우선주", thstrm="3,000"),
        dict(se="주당 현금배당금(원)", stock_knd="보통주", thstrm="1,000"),
        dict(se="현금배당금총액", stock_knd="보통주", thstrm="100000000"),
    ]) == 1000
    assert app.extract_dividend([dict(se="주당 현금배당금(원)", stock_knd="보통주", thstrm="-")]) is None


def test_history_rsi_and_volume_warmup():
    frame = pd.DataFrame({"close": np.arange(1, 62, dtype=float), "volume": [100.] * 60 + [200.]})
    result = app.indicators(frame)
    assert np.isnan(result.rsi.iloc[13])
    assert result.rsi.iloc[14] == 100
    assert np.isnan(result.ma60.iloc[58])
    assert result.ma60.iloc[59] == 30.5
    assert result.volume_ratio.iloc[-1] == 2
    flat = app.indicators(pd.DataFrame({"close": [10.] * 20, "volume": [100.] * 20}))
    assert flat.rsi.iloc[-1] == 50


def test_weekend_and_before_update_fallback(monkeypatch):
    assert app.default_day(datetime(2026, 9, 18, 7, tzinfo=app.KST)) == date(2026, 9, 16)
    called = []
    def fake(key, endpoint, day):
        called.append(day)
        return [] if day == "20260918" else [{"BAS_DD": day}]
    monkeypatch.setattr(app, "krx_rows", fake)
    d, _ = app.latest_rows("test", "endpoint", date(2026, 9, 20))
    assert d == date(2026, 9, 17)
    assert called == ["20260918", "20260917"]


def test_network_exception_hides_key_and_retries_once(monkeypatch):
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        raise requests.exceptions.Timeout("private_key_that_must_not_be_logged")
    monkeypatch.setattr(requests, "get", fail)
    monkeypatch.setattr(app.time, "sleep", lambda _: None)
    with pytest.raises(app.APIError) as result:
        app.http_get("OpenDART", "https://opendart.fss.or.kr/api/list.json")
    assert len(calls) == 2
    assert "private_key" not in str(result.value)


def test_html_response_has_helpful_error():
    response = requests.Response()
    response.status_code = 200
    response._content = b"<html>maintenance</html>"
    with pytest.raises(app.APIError, match="FORMAT"):
        app.json_body(response, "KRX")


def test_no_key_and_demo_navigation(monkeypatch):
    monkeypatch.delenv("KRX_API_KEY", raising=False)
    monkeypatch.delenv("DART_API_KEY", raising=False)
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("미리보기는 API를 호출하면 안 됩니다."))
    ui = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()
    assert not ui.exception
    assert ui.title[0].value == app.TITLE
    assert any("상단" in info.value for info in ui.info)
    ui.radio(key="mode").set_value("디자인 미리보기").run()
    assert not ui.exception
    assert len(ui.get("plotly_chart")) == 3
    assert len(ui.dataframe[0].value) == 3
    ui.checkbox(key="roe_filter").check().run()
    assert len(ui.dataframe[0].value) == 2
    for page in ("재무 상세", "공시", "대시보드"):
        ui.radio(key="page").set_value(page).run()
        assert not ui.exception
    ui.radio(key="mode").set_value("실제 데이터").run()
    assert not ui.exception
    assert not ui.get("plotly_chart")


def fake_response(payload=None, *, content=None, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = content if content is not None else json.dumps(payload).encode()
    result.encoding = "utf-8"
    return result


def simulated_api(url, params=None, **kwargs):
    """문서와 같은 HTTP 응답 구조로 실행 경로 전체를 검사. 실제 인증 시험 아님."""
    if "data-dbg.krx.co.kr" in url:
        day = params["basDd"]
        if "/idx/" in url:
            return fake_response({"OutBlock_1": [dict(BAS_DD=day, IDX_NM="코스피" if "kospi" in url else "코스닥", CLSPRC_IDX="2800", FLUC_RT="0.2")]})
        market = "KOSPI" if "stk_bydd" in url else "KOSDAQ"
        return fake_response({"OutBlock_1": [dict(BAS_DD=day, ISU_CD="005930" if market == "KOSPI" else "123456", ISU_NM="테스트회사" + market,
            MKT_NM=market, TDD_CLSPRC="80000", TDD_OPNPRC="79000", TDD_HGPRC="81000", TDD_LWPRC="78000",
            FLUC_RT="1.2", ACC_TRDVOL="100000", ACC_TRDVAL="8000000000", MKTCAP="80000000000", LIST_SHRS="1000000")]})
    if url.endswith("corpCode.xml"):
        return fake_response(content=zipped_corporation())
    if url.endswith("fnlttSinglAcntAll.json"):
        year = int(params["bsns_year"])
        quarter = {v: k for k, v in app.REPORT_CODES.items()}[params["reprt_code"]]
        rows = financial_reports().get(app.period_number(year, quarter), [])
        return fake_response({"status": "000" if rows else "013", "list": rows})
    if url.endswith("alotMatter.json"):
        return fake_response({"status": "000", "list": [dict(se="주당 현금배당금(원)", stock_knd="보통주", thstrm="1000")]})
    if url.endswith("list.json"):
        return fake_response({"status": "000", "list": [dict(report_nm="자기주식 취득 결정", rcept_no="20260917000001", rcept_dt="20260917")]})
    raise AssertionError(f"Unexpected endpoint {url}")


def test_full_live_ui_with_simulated_http(monkeypatch):
    monkeypatch.setenv("KRX_API_KEY", "FAKE_KRX_FOR_TEST")
    monkeypatch.setenv("DART_API_KEY", "f" * 40)
    monkeypatch.setattr(requests, "get", simulated_api)
    app.krx_rows.clear()
    app.dart_json.clear()
    app.corporations.clear()
    ui = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not ui.exception
    assert not ui.warning
    # 모의 응답으로 이력·재무·공시 조회 경로를 모두 실행.
    next(b for b in ui.button if b.label == "선택 종목 분석 불러오기").click().run(timeout=45)
    assert not ui.exception
    assert len(ui.get("plotly_chart")) == 3
    assert not ui.warning
    ui.radio(key="page").set_value("연결 진단").run()
    ui.button(key="diagnose").click().run(timeout=45)
    assert not ui.exception
    table = ui.dataframe[0].value
    assert set(table["결과"]) == {"정상"}


def test_unauthorized_live_ui_does_not_crash_or_invent_data(monkeypatch):
    monkeypatch.setenv("KRX_API_KEY", "UNAUTHORIZED_TEST_KEY")
    monkeypatch.setenv("DART_API_KEY", "f" * 40)
    monkeypatch.setattr(requests, "get", lambda *a, **k: fake_response({"respCode": "401"}, status=401))
    ui = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()
    assert not ui.exception
    assert len(ui.warning) == 4
    assert not ui.get("plotly_chart")
    assert all("UNAUTHORIZED_TEST_KEY" not in warning.value for warning in ui.warning)
