import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data import fetch, resolve  # noqa: E402
from samples import SAMPLES  # noqa: E402
from scoring import (GURUS, cagr, evaluate, fair_value_gap, grade, linear,  # noqa: E402
                     lynch_category, overall, peg)


def test_linear_both_directions():
    assert linear(10, 25, 10) == 100
    assert linear(25, 25, 10) == 0
    assert linear(17.5, 25, 10) == 50
    assert linear(5, 0, 4) == 100
    assert linear(None, 0, 4) is None


def test_cagr():
    assert round(cagr([100, 121]), 1) == 21.0
    assert round(cagr([100, 110, 121]), 1) == 10.0
    assert cagr([-1, 5]) is None
    assert cagr([5]) is None


def test_all_gurus_score_every_sample_in_range():
    for m in SAMPLES.values():
        for r in evaluate(m):
            assert r.score is None or 0 <= r.score <= 100
            for a in r.axes:
                assert a.score is None or 0 <= a.score <= 100


def test_value_stock_beats_growth_stock_for_value_gurus():
    v = {r.guru.key: r.score for r in evaluate(SAMPLES["DEMO-VALUE"])}
    g = {r.guru.key: r.score for r in evaluate(SAMPLES["DEMO-GROWTH"])}
    for key in ("graham", "lee"):
        assert v[key] > g[key]
    for key in ("fisher",):
        assert g[key] > v[key]


def test_missing_data_is_excluded_not_zero():
    m = {"per": 8, "pbr": 0.7}
    res = {r.guru.key: r for r in evaluate(m)}
    graham = res["graham"]
    assert graham.score is not None and graham.score >= 90
    assert graham.coverage < 1
    # 거의 채점되지 않은 대가는 종합에서 빠짐
    assert overall([graham]) is None or graham.coverage >= 0.5


def test_empty_metrics_do_not_crash():
    results = evaluate({})
    assert len(results) == len(GURUS)
    assert overall(results) is None or overall(results) >= 0


def test_peg_and_fair_value():
    m = SAMPLES["DEMO-GROWTH"]
    assert peg(m) is not None and peg(m) > 0
    gap = fair_value_gap(SAMPLES["DEMO-VALUE"])
    assert gap is not None and gap > 0  # EPS 6400 × ROE 9 = 57600 > 42000


def test_lynch_categories():
    assert lynch_category(SAMPLES["DEMO-TURN"]).startswith("회생주")
    assert lynch_category(SAMPLES["DEMO-VALUE"]).startswith("자산주")
    assert lynch_category(SAMPLES["DEMO-GROWTH"]).startswith("고성장주")


def test_grade_cuts():
    assert [grade(x) for x in (90, 70, 55, 40, 10, None)] == ["A", "B", "C", "D", "E", "-"]


def test_resolve_inputs():
    assert resolve("삼성전자") == ["005930.KS", "005930.KQ"]
    assert resolve("005930") == ["005930.KS", "005930.KQ"]
    assert resolve("aapl") == ["AAPL"]
    assert resolve("035720.KQ") == ["035720.KQ"]
    assert resolve("없는회사이름") == []
    assert resolve("demo-value") == ["DEMO-VALUE"]


def test_fetch_demo_offline():
    m = fetch("DEMO-VALUE", "금리 인하기 (유동성 풍부)")
    k = {r.guru.key: r for r in evaluate(m)}["kostolany"]
    liq = [a for a in k.axes if a.axis == "유동성 환경"][0]
    assert liq.score == 85


def test_build_parses_yfinance_shaped_frames():
    """네트워크 없이 yfinance 형태(최신 열이 먼저)의 DataFrame 파싱 확인."""
    import pandas as pd
    from data import _build

    cols = pd.to_datetime(["2025-12-31", "2024-12-31", "2023-12-31"])
    fin = pd.DataFrame({c: v for c, v in zip(cols, [
        [300.0, 60.0, 45.0, 4.5, 120.0], [250.0, 45.0, 35.0, 3.5, 100.0], [200.0, 30.0, 25.0, 2.5, 80.0]])},
        index=["Total Revenue", "Operating Income", "Net Income", "Diluted EPS", "Gross Profit"])
    bs = pd.DataFrame({c: v for c, v in zip(cols, [
        [300.0, 600.0, 200.0, 100.0, 90.0, 80.0, 20.0], [260.0, 550.0, 180.0, 95.0, 90.0, 70.0, 18.0],
        [230.0, 500.0, 160.0, 90.0, 95.0, 60.0, 15.0]])},
        index=["Stockholders Equity", "Total Assets", "Current Assets", "Current Liabilities",
               "Total Debt", "Cash And Cash Equivalents", "Inventory"])
    cf = pd.DataFrame({c: [40.0] for c in cols}, index=["Free Cash Flow"])
    hist = pd.DataFrame({"Close": [100.0 + i * 0.1 for i in range(250)], "Volume": [1000.0] * 250})

    class FakeTicker:
        info = {"shortName": "Fake", "currency": "KRW", "sharesOutstanding": 10.0}
        financials, balance_sheet, cashflow = fin, bs, cf

    m = _build("123456.KS", FakeTicker(), hist)
    assert m["revenue_hist"] == [200.0, 250.0, 300.0]          # 오래된 → 최신
    assert round(m["per"], 2) == round(m["price"] / 4.5, 2)       # info 없으면 직접 계산
    assert round(m["current_ratio"], 2) == 2.0
    assert round(m["debt_to_equity"]) == 30
    assert m["momentum_12m"] > 0 and m["rsi14"] is not None
    results = evaluate(m)
    assert overall(results) is not None
