"""투자 대가 점수판 — Streamlit 앱.

실행:  streamlit run app.py
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data import DataError, KR_NAMES, fetch
from samples import SAMPLES
from scoring import (GRADE_TEXT, GURUS, LIQUIDITY_SCORE, evaluate, grade, overall,
                     style_scores)

# 범주형 색 (검증된 순서, 3종목까지 동시 비교)
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
MAX_COMPARE = 3

st.set_page_config(page_title="투자 대가 점수판", page_icon="📈", layout="wide")


@st.cache_data(ttl=3600, show_spinner=False)
def load(query: str, env: str) -> dict:
    return fetch(query, env)


def hex_rgba(h: str, a: float) -> str:
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{a})"


def radar(labels: list[str], series: list[tuple[str, list, str]], height: int = 460) -> go.Figure:
    """series: [(이름, 점수 리스트, 색)]. 점수가 None인 축은 0으로 그리고 hover에 '데이터 없음' 표시."""
    fig = go.Figure()
    closed = labels + labels[:1]
    for name, vals, color in series:
        r = [v if v is not None else 0 for v in vals]
        hover = [f"{v:.0f}점" if v is not None else "데이터 없음" for v in vals]
        fig.add_trace(go.Scatterpolar(
            r=r + r[:1], theta=closed, name=name, mode="lines+markers",
            line=dict(color=color, width=2), marker=dict(size=8, color=color),
            fill="toself", fillcolor=hex_rgba(color, 0.18),
            customdata=hover + hover[:1],
            hovertemplate="<b>%{theta}</b><br>" + name + ": %{customdata}<extra></extra>",
        ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(range=[0, 100], tickvals=[20, 40, 60, 80, 100], tickfont=dict(size=10),
                            gridcolor="rgba(128,128,128,0.25)", linecolor="rgba(128,128,128,0.25)"),
            angularaxis=dict(tickfont=dict(size=13), gridcolor="rgba(128,128,128,0.25)"),
            bgcolor="rgba(0,0,0,0)",
        ),
        showlegend=len(series) > 1,
        legend=dict(orientation="h", y=-0.12, x=0.5, xanchor="center"),
        margin=dict(l=60, r=60, t=30, b=40), height=height,
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("종목 입력")
    raw = st.text_input(
        "종목명 · 6자리 코드 · 티커 (쉼표로 최대 3개 비교)",
        value=st.session_state.get("query", "삼성전자"),
        help="예) 삼성전자, 005930, AAPL, MSFT · 네트워크 없이 체험: DEMO-VALUE, DEMO-GROWTH, DEMO-TURN",
    )
    c1, c2 = st.columns(2)
    go_btn = c1.button("분석하기", type="primary", width="stretch")
    if c2.button("데모 보기", width="stretch"):
        st.session_state["query"] = ", ".join(SAMPLES)
        st.rerun()
    if go_btn:
        st.session_state["query"] = raw

    st.divider()
    env = st.radio("현재 금리·유동성 환경 (코스톨라니 평가용)", list(LIQUIDITY_SCORE), index=1)
    picked = st.multiselect("반영할 대가", [g.name for g in GURUS], default=[g.name for g in GURUS])
    with st.expander("이름으로 찾을 수 있는 국내 종목"):
        st.caption(", ".join(sorted(set(KR_NAMES))))
        st.caption("목록에 없으면 6자리 종목코드로 입력하세요.")

query = st.session_state.get("query", "")
guru_keys = [g.key for g in GURUS if g.name in picked]

st.title("📈 투자 대가 점수판")
st.caption("국내외 투자 대가 9인의 원칙으로 종목을 채점합니다. "
           "과거 재무 데이터에 규칙을 적용한 **참고용 점수**이며 투자 권유가 아닙니다.")

if not query:
    st.info("왼쪽에 종목을 입력하고 **분석하기**를 누르세요. 처음이라면 **데모 보기**로 체험할 수 있습니다.")
    st.stop()
if not guru_keys:
    st.warning("반영할 대가를 한 명 이상 선택하세요.")
    st.stop()

# ---------------------------------------------------------------- load
queries = [q.strip() for q in query.split(",") if q.strip()][:MAX_COMPARE]
loaded = []
with st.spinner("데이터를 불러오는 중..."):
    for q in queries:
        try:
            m = load(q, env)
            loaded.append((m, evaluate(m, guru_keys)))
        except DataError as e:
            st.error(str(e))
        except Exception as e:  # noqa: BLE001
            st.error(f"'{q}' 처리 중 오류: {e}")

if not loaded:
    st.stop()

# ---------------------------------------------------------------- summary cards
cols = st.columns(len(loaded))
for col, (m, results), color in zip(cols, loaded, SERIES):
    sc = overall(results)
    g = grade(sc)
    with col:
        st.markdown(f"<div style='border-left:6px solid {color};padding-left:12px'>"
                    f"<div style='font-size:1.05rem;font-weight:600'>{m['name']}</div>"
                    f"<div style='opacity:.7;font-size:.85rem'>{m['ticker']} · {m.get('source', '')}</div>"
                    f"</div>", unsafe_allow_html=True)
        a, b = st.columns(2)
        a.metric("종합 점수", f"{sc:.0f} / 100" if sc is not None else "-")
        b.metric("등급", g)
        st.caption(GRADE_TEXT[g])
        price = m.get("price")
        if price:
            unit = "원" if m.get("currency") == "KRW" else f" {m.get('currency', '')}"
            st.caption(f"현재가 {price:,.0f}{unit}" if unit == "원" else f"현재가 {price:,.2f}{unit}")

# ---------------------------------------------------------------- overall radar
st.subheader("대가별 종합 평가")
left, right = st.columns([3, 2])
labels = [r.guru.name for r in loaded[0][1]]
with left:
    st.plotly_chart(
        radar(labels, [(m["name"], [r.score for r in res], c) for (m, res), c in zip(loaded, SERIES)]),
        width="stretch", config={"displayModeBar": False},
    )
with right:
    rows = []
    for i, gname in enumerate(labels):
        row = {"대가": gname}
        if len(loaded) == 1:
            row["스타일"] = loaded[0][1][i].guru.style
        for m, res in loaded:
            s = res[i].score
            row[m["ticker"] if len(loaded) > 1 else "점수"] = round(s) if s is not None else None
        rows.append(row)
    df = pd.DataFrame(rows)
    score_cols = [c for c in df.columns if c not in ("대가", "스타일")]
    st.dataframe(df, hide_index=True, width="stretch",
                 column_config={c: st.column_config.ProgressColumn(c, min_value=0, max_value=100, format="%d")
                                for c in score_cols})
    st.markdown("**투자 성향별 적합도**")
    srows = []
    for name in style_scores(loaded[0][1]):
        row = {"성향": name}
        for m, res in loaded:
            v = style_scores(res)[name]
            row[m["ticker"] if len(loaded) > 1 else "점수"] = round(v) if v is not None else None
        srows.append(row)
    st.dataframe(pd.DataFrame(srows), hide_index=True, width="stretch",
                 column_config={c: st.column_config.ProgressColumn(c, min_value=0, max_value=100, format="%d")
                                for c in score_cols})

# ---------------------------------------------------------------- per-guru detail
st.subheader("대가별 상세 분석")
tabs = st.tabs([r.guru.name for r in loaded[0][1]])
for i, tab in enumerate(tabs):
    with tab:
        guru = loaded[0][1][i].guru
        st.markdown(f"**{guru.style}** · {guru.region}  \n{guru.philosophy}  \n📚 추천 도서: {guru.book}")
        l2, r2 = st.columns([3, 2])
        axes = [a.axis for a in loaded[0][1][i].axes]
        with l2:
            st.plotly_chart(
                radar(axes, [(m["name"], [a.score for a in res[i].axes], c)
                             for (m, res), c in zip(loaded, SERIES)], height=420),
                width="stretch", config={"displayModeBar": False}, key=f"radar_{guru.key}",
            )
        with r2:
            for m, res in loaded:
                gr = res[i]
                head = f"{m['name']}: **{gr.score:.0f}점**" if gr.score is not None else f"{m['name']}: 데이터 부족"
                st.markdown(head + f" (채점된 항목 {gr.coverage:.0%})")
                if gr.note:
                    st.caption(gr.note)
                st.dataframe(
                    pd.DataFrame([{"포인트": a.axis, "값": a.display,
                                   "점수": round(a.score) if a.score is not None else None,
                                   "기준": a.rule} for a in gr.axes]),
                    hide_index=True, width="stretch",
                    column_config={"점수": st.column_config.ProgressColumn("점수", min_value=0, max_value=100,
                                                                         format="%d")},
                )

with st.expander("점수는 어떻게 계산되나요? (한계 포함)"):
    st.markdown("""
- 대가마다 4~6개의 **중요 포인트(축)**가 있고, 축마다 지표 값을 0~100점으로 바꿉니다. 기준은 각 표의 '기준' 열에 있습니다.
- **대가 점수** = 채점된 축의 평균. **종합 점수** = 축의 절반 이상이 채점된 대가들의 평균.
- 등급: A 80↑ · B 65↑ · C 50↑ · D 35↑ · E 그 미만.
- 경영진 도덕성, 현장 탐방, 사실 수집처럼 **숫자로 잴 수 없는 요소는 재무 지표로 근사**했습니다.
  예) 버핏의 해자 → 영업이익률, 박영옥의 동업 → 내부자 지분율.
- 임계값 일부는 대가의 원칙을 현대 시장에 맞춰 조정한 **추정치**이며, 업종 특성(금융·바이오 등)은 반영하지 않습니다.
- 데이터: Yahoo Finance(yfinance, 비공식). 연간 재무는 보통 최근 4년치이며, 국내 종목은 일부 항목이 비어 있을 수 있습니다.
""")
