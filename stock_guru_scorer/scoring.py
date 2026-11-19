"""대가별 채점 규칙.

각 대가는 4~6개의 '중요 포인트(축)'를 가지며, 축마다 0~100점을 매긴다.
데이터가 없으면 해당 축은 None(채점 제외)으로 두고, 대가 점수는 채점된 축의 평균이다.
임계값은 대가의 저서에 나오는 기준을 출발점으로 삼되, 일부는 현대 시장에 맞춘 추정치다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import Callable, Optional

Metrics = dict


# ---------------------------------------------------------------- helpers
def linear(x: Optional[float], bad: float, good: float) -> Optional[float]:
    """x가 bad이면 0점, good이면 100점, 그 사이는 선형. bad>good이면 낮을수록 좋음."""
    if x is None:
        return None
    if bad == good:
        return 100.0 if x >= good else 0.0
    t = (x - bad) / (good - bad)
    return round(max(0.0, min(1.0, t)) * 100, 1)


def _vals(seq) -> list:
    return [v for v in (seq or []) if v is not None]


def cagr(seq) -> Optional[float]:
    """오래된 값 → 최신 값 순서 리스트의 연평균 성장률(%)."""
    s = _vals(seq)
    if len(s) < 2 or s[0] <= 0 or s[-1] <= 0:
        return None
    return ((s[-1] / s[0]) ** (1 / (len(s) - 1)) - 1) * 100


def growth_ratio(seq) -> Optional[float]:
    """전년 대비 증가한 해의 비율(0~1)."""
    s = _vals(seq)
    if len(s) < 2:
        return None
    ups = sum(1 for a, b in zip(s, s[1:]) if b > a)
    return ups / (len(s) - 1)


def positive_ratio(seq) -> Optional[float]:
    s = _vals(seq)
    if not s:
        return None
    return sum(1 for v in s if v > 0) / len(s)


def avg(seq) -> Optional[float]:
    s = _vals(seq)
    return mean(s) if s else None


def latest(seq) -> Optional[float]:
    s = _vals(seq)
    return s[-1] if s else None


def ratio(a, b) -> Optional[float]:
    if a is None or b in (None, 0):
        return None
    return a / b


def fmt(v, unit: str = "", digits: int = 1) -> str:
    if v is None:
        return "데이터 없음"
    return f"{v:,.{digits}f}{unit}"


# ---------------------------------------------------------------- model
@dataclass
class Criterion:
    axis: str            # 레이더 축 이름
    rule: str            # 채점 기준 설명
    value: Callable[[Metrics], Optional[float]]
    score: Callable[[Optional[float]], Optional[float]]
    unit: str = ""


@dataclass
class Guru:
    key: str
    name: str
    region: str
    style: str
    philosophy: str
    book: str
    criteria: list[Criterion] = field(default_factory=list)


@dataclass
class AxisResult:
    axis: str
    rule: str
    value: Optional[float]
    display: str
    score: Optional[float]


@dataclass
class GuruResult:
    guru: Guru
    axes: list[AxisResult]
    score: Optional[float]
    coverage: float      # 채점된 축 비율
    note: str = ""


# ---------------------------------------------------------------- derived metrics
def roe_series(m: Metrics) -> list:
    out = []
    for ni, eq in zip(m.get("net_income_hist") or [], m.get("equity_hist") or []):
        out.append(ni / eq * 100 if (ni is not None and eq) else None)
    return out


def op_margin_series(m: Metrics) -> list:
    out = []
    for op, rev in zip(m.get("op_income_hist") or [], m.get("revenue_hist") or []):
        out.append(op / rev * 100 if (op is not None and rev) else None)
    return out


def roe_now(m: Metrics) -> Optional[float]:
    return m.get("roe") if m.get("roe") is not None else latest(roe_series(m))


def eps_growth(m: Metrics) -> Optional[float]:
    g = cagr(m.get("eps_hist"))
    return g if g is not None else cagr(m.get("net_income_hist"))


def peg(m: Metrics) -> Optional[float]:
    if m.get("peg") is not None:
        return m["peg"]
    g, per = eps_growth(m), m.get("per")
    if g is None or per is None or g <= 0:
        return None
    return per / g


def fair_value_gap(m: Metrics) -> Optional[float]:
    """김정환식 적정주가(EPS × ROE%) 대비 현재가 상승여력(%)."""
    eps, r, price = latest(m.get("eps_hist")), roe_now(m), m.get("price")
    if eps is None or r is None or not price or eps <= 0 or r <= 0:
        return None
    return (eps * r - price) / price * 100


def fcf_margin(m: Metrics) -> Optional[float]:
    r = ratio(m.get("fcf"), latest(m.get("revenue_hist")))
    return r * 100 if r is not None else None


def rd_ratio(m: Metrics) -> Optional[float]:
    r = ratio(m.get("rd_expense"), latest(m.get("revenue_hist")))
    return r * 100 if r is not None else None


def gpa(m: Metrics) -> Optional[float]:
    return ratio(m.get("gross_profit"), m.get("total_assets"))


def net_cash_ratio(m: Metrics) -> Optional[float]:
    cash, debt, cap = m.get("cash"), m.get("total_debt"), m.get("market_cap")
    if cash is None or cap in (None, 0):
        return None
    return (cash - (debt or 0)) / cap * 100


def inventory_vs_sales(m: Metrics) -> Optional[float]:
    """재고 증가율 - 매출 증가율 (%p). 린치: 재고가 매출보다 빨리 늘면 경고."""
    inv, rev = _vals(m.get("inventory_hist")), _vals(m.get("revenue_hist"))
    if len(inv) < 2 or len(rev) < 2 or inv[-2] <= 0 or rev[-2] <= 0:
        return None
    return (inv[-1] / inv[-2] - 1) * 100 - (rev[-1] / rev[-2] - 1) * 100


def value_composite(m: Metrics) -> Optional[float]:
    parts = _vals([linear(m.get("per"), 30, 5), linear(m.get("pbr"), 3, 0.5),
                   linear(m.get("psr"), 5, 0.5)])
    return mean(parts) if parts else None


def drawdown(m: Metrics) -> Optional[float]:
    p, h = m.get("price"), m.get("high_52w")
    if not p or not h:
        return None
    return (1 - p / h) * 100


LIQUIDITY_SCORE = {"금리 인하기 (유동성 풍부)": 85.0, "중립": 50.0, "금리 인상기 (유동성 축소)": 20.0}


def _positive_per(m: Metrics) -> Optional[float]:
    per = m.get("per")
    return per if (per is not None and per > 0) else None


# ---------------------------------------------------------------- gurus
C = Criterion

GURUS: list[Guru] = [
    Guru("graham", "벤저민 그레이엄", "해외", "정통 가치 (안전마진)",
         "내재가치보다 현저히 싼 가격에 사서 원금을 지킨다. 재무제표 중심의 정량 분석.",
         "《현명한 투자자》", [
             C("저평가(PER)", "PER 25 → 0점, 10 이하 → 100점", _positive_per, lambda v: linear(v, 25, 10)),
             C("자산가치(PBR)", "PBR 3 → 0점, 0.8 이하 → 100점", lambda m: m.get("pbr"), lambda v: linear(v, 3, 0.8)),
             C("그레이엄 수", "PER×PBR 45 → 0점, 15 이하 → 100점 (원칙: 22.5 이하)",
               lambda m: (_positive_per(m) * m["pbr"]) if (_positive_per(m) and m.get("pbr")) else None,
               lambda v: linear(v, 45, 15)),
             C("유동성(유동비율)", "유동비율 1.0 → 0점, 2.5 이상 → 100점 (원칙: 2 이상)",
               lambda m: m.get("current_ratio"), lambda v: linear(v, 1.0, 2.5), "배"),
             C("이익 안정성", "흑자 연도 비율 (전 기간 흑자 = 100점)",
               lambda m: (positive_ratio(m.get("net_income_hist")) or 0) * 100 if m.get("net_income_hist") else None,
               lambda v: v, "%"),
             C("배당", "배당수익률 0% → 0점, 4% 이상 → 100점",
               lambda m: m.get("div_yield"), lambda v: linear(v, 0, 4), "%"),
         ]),
    Guru("buffett", "워런 버핏", "해외", "우량주 장기 보유 (경제적 해자)",
         "강한 해자를 가진 훌륭한 기업을 적정 가격에 사서 오래 보유한다. 경영진의 자본배분 능력을 본다.",
         "《워런 버핏 바이블》, 《워런 버핏의 주주서한》", [
             C("고수익성(ROE)", "평균 ROE 5% → 0점, 20% 이상 → 100점",
               lambda m: avg(roe_series(m)) if _vals(roe_series(m)) else m.get("roe"),
               lambda v: linear(v, 5, 20), "%"),
             C("꾸준함", "ROE 표준편차 10%p → 0점, 2%p 이하 → 100점",
               lambda m: pstdev(_vals(roe_series(m))) if len(_vals(roe_series(m))) >= 3 else None,
               lambda v: linear(v, 10, 2), "%p"),
             C("해자(영업이익률)", "평균 영업이익률 5% → 0점, 25% 이상 → 100점",
               lambda m: avg(op_margin_series(m)), lambda v: linear(v, 5, 25), "%"),
             C("현금창출(FCF)", "FCF 마진 0% → 0점, 15% 이상 → 100점",
               fcf_margin, lambda v: linear(v, 0, 15), "%"),
             C("보수적 부채", "부채/자본 150% → 0점, 30% 이하 → 100점",
               lambda m: m.get("debt_to_equity"), lambda v: linear(v, 150, 30), "%"),
             C("적정 가격", "PER 35 → 0점, 12 이하 → 100점", _positive_per, lambda v: linear(v, 35, 12)),
         ]),
    Guru("lynch", "피터 린치", "해외", "생활 밀착 성장주 (PEG)",
         "생활 속에서 발견한 기업을 재무로 확인한다. 기업을 6유형으로 나눠 다르게 대응한다.",
         "《전설로 떠나는 월가의 영웅》", [
             C("성장 대비 가격(PEG)", "PEG 2 → 0점, 0.5 이하 → 100점", peg, lambda v: linear(v, 2, 0.5)),
             C("이익 성장률", "EPS 연평균 성장 0% → 0점, 25% 이상 → 100점",
               eps_growth, lambda v: linear(v, 0, 25), "%"),
             C("재무 건전성", "부채/자본 150% → 0점, 30% 이하 → 100점",
               lambda m: m.get("debt_to_equity"), lambda v: linear(v, 150, 30), "%"),
             C("재고 관리", "재고증가율-매출증가율 +15%p → 0점, -5%p 이하 → 100점",
               inventory_vs_sales, lambda v: linear(v, 15, -5), "%p"),
             C("현금 여력", "순현금/시가총액 -30% → 0점, 20% 이상 → 100점",
               net_cash_ratio, lambda v: linear(v, -30, 20), "%"),
         ]),
    Guru("fisher", "필립 피셔", "해외", "성장주 (질적 분석)",
         "장기간 매출·이익을 크게 늘릴 잠재력을 본다. 사실 수집(Scuttlebutt)으로 질적 요소를 확인한다.",
         "《위대한 기업에 투자하라》", [
             C("매출 성장", "매출 연평균 성장 0% → 0점, 20% 이상 → 100점",
               lambda m: cagr(m.get("revenue_hist")), lambda v: linear(v, 0, 20), "%"),
             C("성장 지속성", "매출이 증가한 해의 비율",
               lambda m: (growth_ratio(m.get("revenue_hist")) * 100) if growth_ratio(m.get("revenue_hist")) is not None else None,
               lambda v: v, "%"),
             C("마진 개선", "영업이익률 변화 -5%p → 0점, +5%p 이상 → 100점",
               lambda m: (latest(op_margin_series(m)) - _vals(op_margin_series(m))[0])
               if len(_vals(op_margin_series(m))) >= 2 else None,
               lambda v: linear(v, -5, 5), "%p"),
             C("연구개발 투자", "R&D/매출 0% → 0점, 10% 이상 → 100점",
               rd_ratio, lambda v: linear(v, 0, 10), "%"),
             C("수익성", "최근 영업이익률 5% → 0점, 25% 이상 → 100점",
               lambda m: latest(op_margin_series(m)), lambda v: linear(v, 5, 25), "%"),
         ]),
    Guru("kostolany", "앙드레 코스톨라니", "해외", "역발상 · 유동성",
         "주가(강아지)는 결국 가치(주인)로 돌아온다. 대중이 공포에 팔 때 사고, 유동성 흐름을 본다.",
         "《돈, 뜨겁게 사랑하고 차갑게 다루어라》", [
             C("공포 구간(고점 대비 낙폭)", "52주 고점 대비 0% 하락 → 0점, 40% 이상 하락 → 100점",
               drawdown, lambda v: linear(v, 0, 40), "%"),
             C("과매도(RSI)", "RSI 70 → 0점, 30 이하 → 100점",
               lambda m: m.get("rsi14"), lambda v: linear(v, 70, 30)),
             C("대중 소외", "최근 20일/1년 평균 거래량 1.5배 → 0점, 0.6배 이하 → 100점",
               lambda m: m.get("volume_ratio"), lambda v: linear(v, 1.5, 0.6), "배"),
             C("버틸 체력", "부채/자본 200% → 0점, 50% 이하 → 100점",
               lambda m: m.get("debt_to_equity"), lambda v: linear(v, 200, 50), "%"),
             C("유동성 환경", "사이드바에서 선택한 금리 환경 (인하기 85 / 중립 50 / 인상기 20)",
               lambda m: LIQUIDITY_SCORE.get(m.get("liquidity_env", "중립"), 50.0), lambda v: v),
         ]),
    Guru("park", "박영옥", "국내", "농심(農心) 동업 투자",
         "성장하는 강소기업을 골라 대주주와 동업한다는 마음으로 수년간 함께한다.",
         "《주식, 농부처럼 투자하라》", [
             C("꾸준한 이익 성장", "순이익이 증가한 해의 비율",
               lambda m: (growth_ratio(m.get("net_income_hist")) * 100)
               if growth_ratio(m.get("net_income_hist")) is not None else None,
               lambda v: v, "%"),
             C("수익성(ROE)", "ROE 5% → 0점, 15% 이상 → 100점", roe_now, lambda v: linear(v, 5, 15), "%"),
             C("주주환원(배당)", "배당수익률 0% → 0점, 4% 이상 → 100점",
               lambda m: m.get("div_yield"), lambda v: linear(v, 0, 4), "%"),
             C("대주주 동행", "내부자(대주주) 지분 5% → 0점, 40% 이상 → 100점",
               lambda m: m.get("insider_pct"), lambda v: linear(v, 5, 40), "%"),
             C("합리적 가격", "PER 30 → 0점, 10 이하 → 100점", _positive_per, lambda v: linear(v, 30, 10)),
         ]),
    Guru("kim", "김정환", "국내", "가치 기반 모멘텀 (ROE·PER)",
         "기업의 적정 주가를 계산해 저평가 구간에서 산다. ROE와 PER로 내재가치를 가늠한다.",
         "《나의 첫 투자 수업》", [
             C("적정가 괴리", "적정주가(EPS×ROE) 대비 상승여력 -30% → 0점, +50% 이상 → 100점",
               fair_value_gap, lambda v: linear(v, -30, 50), "%"),
             C("ROE 수준", "ROE 5% → 0점, 20% 이상 → 100점", roe_now, lambda v: linear(v, 5, 20), "%"),
             C("PER 수준", "PER 25 → 0점, 8 이하 → 100점", _positive_per, lambda v: linear(v, 25, 8)),
             C("이익 모멘텀", "EPS 성장 -10% → 0점, +20% 이상 → 100점",
               eps_growth, lambda v: linear(v, -10, 20), "%"),
         ]),
    Guru("kang", "강환국", "국내", "퀀트 (계량)",
         "감정을 배제하고 데이터로 검증된 지표(밸류·모멘텀·퀄리티)에 따라 기계적으로 매매한다.",
         "《할 수 있다! 퀀트 투자》", [
             C("밸류 종합", "PER·PBR·PSR 각각을 점수화한 평균", value_composite, lambda v: v),
             C("모멘텀", "12개월 수익률 -20% → 0점, +40% 이상 → 100점",
               lambda m: m.get("momentum_12m"), lambda v: linear(v, -20, 40), "%"),
             C("퀄리티(GP/A)", "매출총이익/총자산 0.1 → 0점, 0.4 이상 → 100점",
               gpa, lambda v: linear(v, 0.1, 0.4), "", ),
             C("저변동성", "연환산 변동성 60% → 0점, 20% 이하 → 100점",
               lambda m: m.get("volatility"), lambda v: linear(v, 60, 20), "%"),
         ]),
    Guru("lee", "이채원", "국내", "한국형 정통 가치",
         "시장에서 소외돼 자산·수익 가치 대비 지나치게 싼 종목을 사서 제값을 받을 때까지 기다린다.",
         "《이채원의 가치투자》", [
             C("자산가치(PBR)", "PBR 2 → 0점, 0.6 이하 → 100점", lambda m: m.get("pbr"), lambda v: linear(v, 2, 0.6)),
             C("수익가치(PER)", "PER 20 → 0점, 7 이하 → 100점", _positive_per, lambda v: linear(v, 20, 7)),
             C("순현금", "순현금/시가총액 -20% → 0점, 30% 이상 → 100점",
               net_cash_ratio, lambda v: linear(v, -20, 30), "%"),
             C("시장 소외", "최근 20일/1년 평균 거래량 1.5배 → 0점, 0.5배 이하 → 100점",
               lambda m: m.get("volume_ratio"), lambda v: linear(v, 1.5, 0.5), "배"),
             C("배당", "배당수익률 0% → 0점, 5% 이상 → 100점",
               lambda m: m.get("div_yield"), lambda v: linear(v, 0, 5), "%"),
         ]),
]

GURU_BY_KEY = {g.key: g for g in GURUS}


# ---------------------------------------------------------------- lynch 6 types
CYCLICAL_SECTORS = {"Energy", "Basic Materials", "Industrials", "Consumer Cyclical", "Real Estate"}


def lynch_category(m: Metrics) -> str:
    ni = _vals(m.get("net_income_hist"))
    g = eps_growth(m)
    if len(ni) >= 2 and min(ni[:-1]) < 0 < ni[-1]:
        return "회생주 (적자에서 흑자로 전환)"
    if m.get("pbr") is not None and m["pbr"] < 0.8:
        return "자산주 (자산 대비 저평가)"
    if m.get("sector") in CYCLICAL_SECTORS:
        return "경기순환주 (업황에 따라 이익 변동)"
    if g is not None and g >= 20:
        return "고성장주 (연 20% 이상 성장)"
    if g is not None and g >= 10:
        return "대형우량주 (연 10~20% 성장)" if (m.get("market_cap") or 0) > 0 else "대형우량주"
    if g is not None:
        return "저성장주 (연 10% 미만 성장)"
    return "분류 불가 (데이터 부족)"


# ---------------------------------------------------------------- evaluate
def evaluate_guru(guru: Guru, m: Metrics) -> GuruResult:
    axes = []
    for c in guru.criteria:
        try:
            v = c.value(m)
        except (TypeError, ZeroDivisionError, KeyError, ValueError):
            v = None
        s = c.score(v) if v is not None else None
        axes.append(AxisResult(c.axis, c.rule, v, fmt(v, c.unit, 2 if c.unit == "" else 1), s))
    scored = [a.score for a in axes if a.score is not None]
    score = round(mean(scored), 1) if scored else None
    note = f"피터 린치 분류: {lynch_category(m)}" if guru.key == "lynch" else ""
    return GuruResult(guru, axes, score, len(scored) / len(axes), note)


def evaluate(m: Metrics, guru_keys: Optional[list[str]] = None) -> list[GuruResult]:
    gurus = [GURU_BY_KEY[k] for k in guru_keys] if guru_keys else GURUS
    return [evaluate_guru(g, m) for g in gurus]


def overall(results: list[GuruResult]) -> Optional[float]:
    """대가 점수의 평균. 축의 절반 미만만 채점된 대가는 신뢰도가 낮아 제외한다."""
    s = [r.score for r in results if r.score is not None and r.coverage >= 0.5]
    return round(mean(s), 1) if s else None


def grade(score: Optional[float]) -> str:
    if score is None:
        return "-"
    for cut, g in ((80, "A"), (65, "B"), (50, "C"), (35, "D")):
        if score >= cut:
            return g
    return "E"


GRADE_TEXT = {
    "A": "여러 대가가 공통으로 높게 평가 (매력적)",
    "B": "대체로 긍정적 (관심 종목)",
    "C": "장단점 혼재 (추가 분석 필요)",
    "D": "다수 기준 미달 (신중)",
    "E": "대가 기준과 거리가 멂",
    "-": "데이터 부족",
}

STYLE_GROUPS = {
    "안정·보수형": ["graham", "lee"],
    "우량주 장기보유형": ["buffett", "fisher"],
    "생활·성장 발굴형": ["lynch", "park"],
    "데이터·원칙형": ["kang", "kim"],
    "역발상형": ["kostolany"],
}


def style_scores(results: list[GuruResult]) -> dict[str, Optional[float]]:
    by = {r.guru.key: r for r in results}
    out = {}
    for name, keys in STYLE_GROUPS.items():
        s = [by[k].score for k in keys if k in by and by[k].score is not None]
        out[name] = round(mean(s), 1) if s else None
    return out
