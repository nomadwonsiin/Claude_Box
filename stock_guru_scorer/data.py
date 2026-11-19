"""종목 입력 해석 + Yahoo Finance(yfinance)로 지표 수집.

- 미국: AAPL, MSFT 같은 티커
- 한국: 6자리 종목코드(005930) 또는 등록된 종목명(삼성전자). 코스피(.KS) → 코스닥(.KQ) 순으로 찾는다.
- 'DEMO-'로 시작하면 네트워크 없이 samples.py의 가상 데이터를 쓴다.
"""
from __future__ import annotations

import math
import re
from typing import Optional

from samples import SAMPLES

# 자주 찾는 국내 종목 (이름 → 코드). 여기에 없는 종목은 6자리 코드로 입력.
KR_NAMES = {
    "삼성전자": "005930", "SK하이닉스": "000660", "LG에너지솔루션": "373220",
    "삼성바이오로직스": "207940", "현대차": "005380", "현대자동차": "005380", "기아": "000270",
    "셀트리온": "068270", "KB금융": "105560", "신한지주": "055550", "POSCO홀딩스": "005490",
    "포스코홀딩스": "005490", "NAVER": "035420", "네이버": "035420", "카카오": "035720",
    "LG화학": "051910", "삼성SDI": "006400", "현대모비스": "012330", "삼성물산": "028260",
    "하나금융지주": "086790", "우리금융지주": "316140", "삼성생명": "032830", "삼성화재": "000810",
    "LG전자": "066570", "SK이노베이션": "096770", "SK텔레콤": "017670", "KT": "030200",
    "KT&G": "033780", "한국전력": "015760", "HMM": "011200", "고려아연": "010130",
    "한화에어로스페이스": "012450", "HD현대중공업": "329180", "두산에너빌리티": "034020",
    "LG": "003550", "SK": "034730", "삼성전기": "009150", "아모레퍼시픽": "090430",
    "CJ제일제당": "097950", "오리온": "271560", "농심": "004370", "엔씨소프트": "036570",
    "크래프톤": "259960", "넷마블": "251270", "에코프로": "086520", "에코프로비엠": "247540",
    "알테오젠": "196170", "HLB": "028300", "리노공업": "058470", "삼성중공업": "010140",
    "한미반도체": "042700", "하이브": "352820", "이마트": "139480", "롯데쇼핑": "023530",
    "GS": "078930", "메리츠금융지주": "138040", "기업은행": "024110", "S-Oil": "010950",
}


def resolve(query: str) -> list[str]:
    """입력값을 시도해 볼 Yahoo 티커 후보 목록으로 바꾼다."""
    q = query.strip()
    if not q:
        return []
    if q.upper().startswith("DEMO-"):
        return [q.upper()]
    if q in KR_NAMES:
        q = KR_NAMES[q]
    else:
        upper = {k.upper(): v for k, v in KR_NAMES.items()}
        if q.upper() in upper:
            q = upper[q.upper()]
    if re.fullmatch(r"\d{6}", q):
        return [f"{q}.KS", f"{q}.KQ"]
    if re.fullmatch(r"\d{6}\.(KS|KQ)", q.upper()):
        return [q.upper()]
    if re.search(r"[가-힣]", q):
        return []  # 미등록 한글 종목명 → search_name()으로 처리
    return [q.upper()]


def search_name(query: str) -> list[str]:
    """yfinance 검색 API로 종목명 → 티커 후보. 실패하면 빈 목록."""
    try:
        import yfinance as yf
        res = yf.Search(query, max_results=5)
        return [q["symbol"] for q in res.quotes if q.get("symbol")]
    except Exception:
        return []


# ---------------------------------------------------------------- helpers
def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(f) or math.isinf(f)) else f


def _row(df, *names) -> list:
    """재무제표 DataFrame에서 행을 찾아 오래된 해 → 최신 해 순서 리스트로."""
    if df is None or getattr(df, "empty", True):
        return []
    for n in names:
        if n in df.index:
            vals = [_num(v) for v in df.loc[n].tolist()]
            vals = list(reversed(vals))  # yfinance는 최신 열이 먼저
            while vals and vals[0] is None:
                vals.pop(0)
            return vals
    return []


def _last(seq) -> Optional[float]:
    s = [v for v in seq if v is not None]
    return s[-1] if s else None


def _rsi(closes, period: int = 14) -> Optional[float]:
    if len(closes) <= period:
        return None
    gains, losses = [], []
    for a, b in zip(closes[-period - 1:], closes[-period:]):
        d = b - a
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag, al = sum(gains) / period, sum(losses) / period
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


# ---------------------------------------------------------------- fetch
class DataError(Exception):
    pass


def fetch(query: str, liquidity_env: str = "중립") -> dict:
    """종목 하나의 지표 dict를 돌려준다. 못 찾으면 DataError."""
    candidates = resolve(query) or search_name(query)
    if not candidates:
        raise DataError(f"'{query}'에 해당하는 종목을 찾지 못했습니다. 6자리 코드나 티커로 입력해 보세요.")

    if candidates[0].startswith("DEMO-"):
        if candidates[0] not in SAMPLES:
            raise DataError(f"데모 종목은 {', '.join(SAMPLES)} 만 있습니다.")
        m = dict(SAMPLES[candidates[0]])
        m["liquidity_env"] = liquidity_env
        return m

    import yfinance as yf

    last_err = None
    for sym in candidates:
        try:
            tk = yf.Ticker(sym)
            hist = tk.history(period="1y", auto_adjust=True)
            if hist is None or hist.empty:
                continue
            m = _build(sym, tk, hist)
            m["liquidity_env"] = liquidity_env
            return m
        except Exception as e:  # 네트워크/파싱 오류
            last_err = e
    msg = f"'{query}' 데이터를 가져오지 못했습니다 (시도: {', '.join(candidates)})."
    if last_err:
        msg += f" 오류: {last_err}"
    raise DataError(msg)


def _build(sym: str, tk, hist) -> dict:
    try:
        info = tk.info or {}
    except Exception:
        info = {}
    fin, bs, cf = tk.financials, tk.balance_sheet, tk.cashflow

    closes = [float(c) for c in hist["Close"].tolist()]
    vols = [float(v) for v in hist["Volume"].tolist()]
    price = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice")) or closes[-1]

    revenue = _row(fin, "Total Revenue", "Operating Revenue")
    op_income = _row(fin, "Operating Income", "EBIT")
    net_income = _row(fin, "Net Income Common Stockholders", "Net Income")
    eps = _row(fin, "Diluted EPS", "Basic EPS")
    gross = _row(fin, "Gross Profit")
    rd = _row(fin, "Research And Development")
    equity = _row(bs, "Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest")
    assets = _row(bs, "Total Assets")
    cur_a = _row(bs, "Current Assets")
    cur_l = _row(bs, "Current Liabilities")
    debt = _row(bs, "Total Debt")
    cash = _row(bs, "Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents")
    inventory = _row(bs, "Inventory")
    fcf = _row(cf, "Free Cash Flow")

    shares = _num(info.get("sharesOutstanding"))
    mcap = _num(info.get("marketCap")) or (price * shares if shares else None)
    eq_last, rev_last = _last(equity), _last(revenue)

    per = _num(info.get("trailingPE"))
    if per is None and _last(eps):
        per = price / _last(eps) if _last(eps) > 0 else None
    pbr = _num(info.get("priceToBook"))
    if pbr is None and mcap and eq_last:
        pbr = mcap / eq_last if eq_last > 0 else None
    psr = _num(info.get("priceToSalesTrailing12Months"))
    if psr is None and mcap and rev_last:
        psr = mcap / rev_last
    de = _num(info.get("debtToEquity"))
    if de is None and _last(debt) is not None and eq_last:
        de = _last(debt) / eq_last * 100
    cr = _num(info.get("currentRatio"))
    if cr is None and _last(cur_a) and _last(cur_l):
        cr = _last(cur_a) / _last(cur_l)

    div_rate = _num(info.get("dividendRate")) or _num(info.get("trailingAnnualDividendRate"))
    div_yield = div_rate / price * 100 if (div_rate and price) else 0.0

    roe = _num(info.get("returnOnEquity"))
    insider = _num(info.get("heldPercentInsiders"))
    rets = [b / a - 1 for a, b in zip(closes, closes[1:]) if a]
    vol = None
    if len(rets) > 20:
        mu = sum(rets) / len(rets)
        vol = math.sqrt(sum((r - mu) ** 2 for r in rets) / len(rets)) * math.sqrt(252) * 100

    return {
        "ticker": sym,
        "name": info.get("longName") or info.get("shortName") or sym,
        "currency": info.get("currency") or ("KRW" if sym.endswith((".KS", ".KQ")) else "USD"),
        "sector": info.get("sector"),
        "price": price,
        "market_cap": mcap,
        "per": per,
        "pbr": pbr,
        "psr": psr,
        "peg": _num(info.get("trailingPegRatio")) or _num(info.get("pegRatio")),
        "roe": roe * 100 if roe is not None else None,
        "div_yield": div_yield,
        "debt_to_equity": de,
        "current_ratio": cr,
        "insider_pct": insider * 100 if insider is not None else None,
        "revenue_hist": revenue,
        "op_income_hist": op_income,
        "net_income_hist": net_income,
        "eps_hist": eps,
        "equity_hist": equity,
        "inventory_hist": inventory,
        "gross_profit": _last(gross),
        "total_assets": _last(assets),
        "rd_expense": _last(rd),
        "fcf": _last(fcf),
        "cash": _last(cash) or _num(info.get("totalCash")),
        "total_debt": _last(debt) if debt else _num(info.get("totalDebt")),
        "high_52w": _num(info.get("fiftyTwoWeekHigh")) or max(closes),
        "momentum_12m": (closes[-1] / closes[0] - 1) * 100 if closes[0] else None,
        "rsi14": _rsi(closes),
        "volatility": vol,
        "volume_ratio": (sum(vols[-20:]) / 20) / (sum(vols) / len(vols)) if len(vols) >= 60 and sum(vols) else None,
        "source": "Yahoo Finance (yfinance)",
    }
