from datetime import datetime
import warnings
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

# ==========================================
# 版本號定義
# ==========================================
APP_VERSION = "v2.6.0"
BUILD_DATE = "2026-09-01"
BUILD_TAG = "Auto Day-Trend & Intraday Anti-Fakeout Engine"

warnings.filterwarnings("ignore")

# 頁面配置
st.set_page_config(
    page_title=f"美股期權量化埋伏系統 ({APP_VERSION})",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 自訂暗黑交易終端 CSS
st.markdown(
    """
<style>
    .metric-card {
        background: rgba(30, 41, 59, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
        padding: 16px;
    }
    .version-badge {
        background: rgba(16, 185, 129, 0.15);
        color: #10b981;
        border: 1px solid rgba(16, 185, 129, 0.3);
        padding: 2px 8px;
        border-radius: 6px;
        font-size: 12px;
        font-family: monospace;
        font-weight: bold;
    }
    .stDataFrame { border-radius: 12px; overflow: hidden; }
</style>
""",
    unsafe_allow_html=True,
)

# 側邊欄配置
st.sidebar.title("⚙️ 策略參數配置")
st.sidebar.markdown(f"系統核心版本：`{APP_VERSION}`")

dte_min, dte_max = st.sidebar.slider(
    "期權到期日範圍 (DTE)", min_value=14, max_value=60, value=(20, 45)
)
atr_multiplier = st.sidebar.slider(
    "肯特納通道 ATR 倍數 (收斂靈敏度)",
    min_value=1.2,
    max_value=2.5,
    value=1.8,
    step=0.1,
)
max_budget = st.sidebar.number_input(
    "小資金單注最大預算 ($)",
    min_value=20,
    max_value=2000,
    value=350,
    step=50,
)

# 最低盈虧比門檻過濾
min_rr_ratio = st.sidebar.slider(
    "🔥 最低盈虧比門檻 (1 : X)",
    min_value=1.0,
    max_value=3.0,
    value=1.5,
    step=0.1,
    help="低於此盈虧比的合約組合將自動被系統剔除，不予顯示",
)

# 新增：開盤走勢防跳水過濾開關
enforce_intraday_trend = st.sidebar.checkbox(
    "🛡️ 啟用盤中防假突破過濾 (現價與開盤價同向)",
    value=True,
    help="做多必須現價 >= 開盤價且 > 20MA（紅轉綠跳水直接剔除）；做空必須現價 <= 開盤價且 < 20MA",
)

st.sidebar.markdown("### 🎯 止盈止損參數")
tp_ratio_min = (
    st.sidebar.slider("最小止盈比率 (%)", min_value=30, max_value=80, value=50)
    / 100.0
)
tp_ratio_max = (
    st.sidebar.slider("理想止盈比率 (%)", min_value=50, max_value=90, value=70)
    / 100.0
)
sl_ratio = (
    st.sidebar.slider("剛性止損比率 (%)", min_value=20, max_value=60, value=40)
    / 100.0
)

st.sidebar.markdown("---")
st.sidebar.caption(f"構建版本：`{APP_VERSION}` | `{BUILD_DATE}`\n\n特性：`{BUILD_TAG}`")

# 頂部標題展示
col_title, col_ver = st.columns([4, 1])
with col_title:
    st.markdown(
        f"## 📊 美股小資金期權量化埋伏儀表板 <span class='version-badge'>{APP_VERSION}</span>",
        unsafe_allow_html=True,
    )
    st.caption("基於 TTM Squeeze 波動率收斂 + 盤中開盤價防跳水過濾 + 跨價期權組合 (Vertical Spreads)")
with col_ver:
    st.markdown(
        f"<div style='text-align:right; font-size:12px; color:#94a3b8;'>核心引擎：<br><strong style='color:#e2e8f0;'>Release {APP_VERSION}</strong></div>",
        unsafe_allow_html=True,
    )

DEFAULT_WATCHLIST = [
    "SPY", "QQQ", "IWM", "NVDA", "TSLA", "AMD", "AAPL", "MSFT", "AMZN",
    "META", "GOOGL", "PLTR", "COIN", "AVGO", "INTC", "BA", "NFLX", "BABA",
    "CRM", "ORCL", "UBER", "DIS", "SMCI", "MU", "ARM", "PANW", "CRWD",
    "SNOW", "SHOP", "MARA", "MSTR", "HOOD", "AFRM", "SOFI", "UPST", "RBLX",
    "DKNG", "PDD", "JD", "NIO", "XOM", "CVX", "JPM", "GS", "BAC", "LLY",
    "UNH", "CAT", "GE", "COST", "WMT"
]

def run_scan(tickers, atr_mult, check_intraday):
    candidates = []
    for sym in tickers:
        try:
            df = yf.Ticker(sym).history(period="6mo", interval="1d")
            if df.empty or len(df) < 30:
                continue
            close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"]
            open_p = df["Open"]

            ma20 = close.rolling(20).mean()
            std20 = close.rolling(20).std()
            bb_upper = ma20 + (2 * std20)
            bb_lower = ma20 - (2 * std20)

            tr1 = high - low
            tr2 = (high - close.shift(1)).abs()
            tr3 = (low - close.shift(1)).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(20).mean()
            kc_upper = ma20 + (atr_mult * atr)
            kc_lower = ma20 - (atr_mult * atr)

            is_squeezing = (bb_lower > kc_lower) & (bb_upper < kc_upper)
            recent_squeeze = bool(is_squeezing.tail(5).any())

            curr_close = float(close.iloc[-1])
            curr_open = float(open_p.iloc[-1])
            curr_ma20 = float(ma20.iloc[-1])

            # ---------------- 方向判斷與防跳水核心邏輯 ----------------
            if check_intraday:
                # 做多條件：現價在 20MA 之上 且 現價 >= 今日開盤價 (實體陽燭，非衝高回落)
                is_bullish = (curr_close >= curr_ma20) and (curr_close >= curr_open)
                # 做空條件：現價在 20MA 之下 且 現價 <= 今日開盤價 (實體陰燭，非低開反彈)
                is_bearish = (curr_close < curr_ma20) and (curr_close <= curr_open)
                
                # 如果處於矛盾狀態（例如高開跳水跌破開盤但仍在20MA上，或低開衝高），視為雜訊直接不發出信號
                if not is_bullish and not is_bearish:
                    continue
                direction_label = "多頭 (CALL)" if is_bullish else "空頭 (PUT)"
            else:
                is_bullish = curr_close >= curr_ma20
                direction_label = "多頭 (CALL)" if is_bullish else "空頭 (PUT)"

            vol_ma20 = float(vol.rolling(20).mean().iloc[-1])
            curr_vol = float(vol.iloc[-1])
            vol_ratio = round(curr_vol / vol_ma20, 2) if vol_ma20 > 0 else 1.0

            bb_w = bb_upper.iloc[-1] - bb_lower.iloc[-1]
            kc_w = kc_upper.iloc[-1] - kc_lower.iloc[-1]
            comp_ratio = round(float(bb_w / kc_w), 2) if kc_w > 0 else 1.0

            day_change_pct = round(((curr_close - curr_open) / curr_open) * 100, 2)

            if recent_squeeze or comp_ratio < 1.05:
                candidates.append({
                    "Symbol": sym,
                    "Direction": direction_label,
                    "Price": round(curr_close, 2),
                    "Open": round(curr_open, 2),
                    "當日漲跌(%)": f"{day_change_pct}%",
                    "20MA": round(curr_ma20, 2),
                    "Vol_Ratio": vol_ratio,
                    "壓縮比率": comp_ratio,
                    "Squeeze現狀": bool(is_squeezing.iloc[-1]),
                })
        except Exception:
            continue

    if not candidates:
        return pd.DataFrame(columns=["Symbol", "Direction", "Price", "Open", "當日漲跌(%)", "20MA", "Vol_Ratio", "壓縮比率", "Squeeze現狀"])
    
    return pd.DataFrame(candidates)

def get_options_spreads(candidates_df, d_min, d_max, tp_min_pct, tp_max_pct, sl_pct, min_rr):
    columns_list = [
        "標的", "方向", "現價", "到期日", "組合策略", "買入腿 (Long)",
        "賣出腿 (Short)", "淨成本 ($)", "最大獲利 ($)", "盈虧比",
        "建議止盈獲利 ($)", "目標平倉單價 ($)", "剛性止損 ($)", "Cost_Num", "RR_Num"
    ]
    if candidates_df.empty:
        return pd.DataFrame(columns=columns_list)
        
    today = datetime.today()
    spreads = []

    for _, row in candidates_df.head(15).iterrows():
        sym, curr_price, direction = row["Symbol"], row["Price"], row["Direction"]
        try:
            ticker = yf.Ticker(sym)
            expirations = ticker.options
            if not expirations:
                continue

            target_exp, target_dte = None, None
            for exp in expirations:
                dte = (datetime.strptime(exp, "%Y-%m-%d") - today).days
                if d_min <= dte <= d_max:
                    target_exp, target_dte = exp, dte
                    break
            if not target_exp:
                continue

            chain = ticker.option_chain(target_exp)

            # ---------------- 多頭 (Bull Call Spread) ----------------
            if "CALL" in direction:
                calls = chain.calls.copy()
                if calls.empty:
                    continue
                calls = calls.sort_values("strike", ascending=True)

                b_cands = calls[calls["strike"] >= curr_price]
                s_cands = calls[calls["strike"] >= curr_price * 1.03]
                if b_cands.empty or s_cands.empty:
                    continue

                b_leg = b_cands.iloc[0]
                s_valid = s_cands[s_cands["strike"] > b_leg["strike"]]
                if s_valid.empty:
                    continue
                s_leg = s_valid.iloc[0]

                b_p = b_leg["ask"] if b_leg["ask"] > 0 else b_leg["lastPrice"]
                s_p = s_leg["bid"] if s_leg["bid"] > 0 else (s_leg["lastPrice"] if s_leg["lastPrice"] < b_p else 0.0)

                net_debit = max(0.05, round(b_p - s_p, 2))
                cost = round(net_debit * 100, 2)
                spread_width = s_leg["strike"] - b_leg["strike"]
                max_profit = round((spread_width * 100) - cost, 2)
                if max_profit <= 0:
                    continue
                rr = round(max_profit / cost, 2) if cost > 0 else 0

                if rr < min_rr:
                    continue

                tp_amt_min = round(max_profit * tp_min_pct, 1)
                tp_amt_max = round(max_profit * tp_max_pct, 1)
                target_close_price_min = round(net_debit + (tp_amt_min / 100.0), 2)
                target_close_price_max = round(net_debit + (tp_amt_max / 100.0), 2)
                sl_amt = round(cost * sl_pct, 1)

                spreads.append({
                    "標的": sym,
                    "方向": "🟢 多 (Bull)",
                    "現價": curr_price,
                    "到期日": f"{target_exp} ({target_dte}D)",
                    "組合策略": "Bull Call Spread",
                    "買入腿 (Long)": f"${b_leg['strike']} Call (@{b_p})",
                    "賣出腿 (Short)": f"${s_leg['strike']} Call (@{s_p})",
                    "淨成本 ($)": cost,
                    "最大獲利 ($)": max_profit,
                    "盈虧比": f"1 : {rr}",
                    "建議止盈獲利 ($)": f"+${tp_amt_min} ~ +${tp_amt_max}",
                    "目標平倉單價 ($)": f"${target_close_price_min} ~ ${target_close_price_max}",
                    "剛性止損 ($)": f"-${sl_amt} (40%)",
                    "Cost_Num": cost,
                    "RR_Num": rr,
                })

            # ---------------- 空頭 (Bear Put Spread) ----------------
            else:
                puts = chain.puts.copy()
                if puts.empty:
                    continue
                puts = puts.sort_values("strike", ascending=True)

                b_cands = puts[puts["strike"] <= curr_price]
                s_cands = puts[puts["strike"] <= curr_price * 0.97]
                if b_cands.empty or s_cands.empty:
                    continue

                b_leg = b_cands.iloc[-1]
                s_valid = s_cands[s_cands["strike"] < b_leg["strike"]]
                if s_valid.empty:
                    continue
                s_leg = s_valid.iloc[-1]

                b_p = b_leg["ask"] if b_leg["ask"] > 0 else b_leg["lastPrice"]
                s_p = s_leg["bid"] if s_leg["bid"] > 0 else (s_leg["lastPrice"] if s_leg["lastPrice"] < b_p else 0.0)

                net_debit = max(0.05, round(b_p - s_p, 2))
                cost = round(net_debit * 100, 2)
                spread_width = b_leg["strike"] - s_leg["strike"]
                max_profit = round((spread_width * 100) - cost, 2)
                if max_profit <= 0:
                    continue
                rr = round(max_profit / cost, 2) if cost > 0 else 0

                if rr < min_rr:
                    continue

                tp_amt_min = round(max_profit * tp_min_pct, 1)
                tp_amt_max = round(max_profit * tp_max_pct, 1)
                target_close_price_min = round(net_debit + (tp_amt_min / 100.0), 2)
                target_close_price_max = round(net_debit + (tp_amt_max / 100.0), 2)
                sl_amt = round(cost * sl_pct, 1)

                spreads.append({
                    "標的": sym,
                    "方向": "🔴 空 (Bear)",
                    "現價": curr_price,
                    "到期日": f"{target_exp} ({target_dte}D)",
                    "組合策略": "Bear Put Spread",
                    "買入腿 (Long)": f"${b_leg['strike']} Put (@{b_p})",
                    "賣出腿 (Short)": f"${s_leg['strike']} Put (@{s_p})",
                    "淨成本 ($)": cost,
                    "最大獲利 ($)": max_profit,
                    "盈虧比": f"1 : {rr}",
                    "建議止盈獲利 ($)": f"+${tp_amt_min} ~ +${tp_amt_max}",
                    "目標平倉單價 ($)": f"${target_close_price_min} ~ ${target_close_price_max}",
                    "剛性止損 ($)": f"-${sl_amt} (40%)",
                    "Cost_Num": cost,
                    "RR_Num": rr,
                })
        except Exception:
            continue

    if not spreads:
        return pd.DataFrame(columns=columns_list)

    df_out = pd.DataFrame(spreads)
    df_out = df_out.sort_values(by="RR_Num", ascending=False)
    return df_out

# 執行按鈕
if st.button("🚀 開始執行全市場量化掃描"):
    with st.spinner("正在掃描市場 K 線與期權鏈數據..."):
        cand_df = run_scan(DEFAULT_WATCHLIST, atr_multiplier, enforce_intraday_trend)
        st.session_state["cand_df"] = cand_df
        st.session_state["spread_df"] = get_options_spreads(
            cand_df, dte_min, dte_max, tp_ratio_min, tp_ratio_max, sl_ratio, min_rr_ratio
        )

if "cand_df" in st.session_state:
    cand_df = st.session_state["cand_df"]
    spread_df = st.session_state["spread_df"]

    squeeze_count = 0
    if not cand_df.empty and "Squeeze現狀" in cand_df.columns:
        squeeze_count = len(cand_df[cand_df["Squeeze現狀"]])

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("掃描標的池", f"{len(DEFAULT_WATCHLIST)} 隻")
    col2.metric("Squeeze 蓄勢中", f"{squeeze_count} 隻")
    col3.metric("高賠率期權組合", f"{len(spread_df)} 組")
    col4.metric(f"預算篩選 (< ${max_budget})", f"{max_budget} 美元")

    st.markdown(f"### 🎯 精選高性價比期權組合 (已過濾 RR ≥ 1 : {min_rr_ratio})")
    if not spread_df.empty and "Cost_Num" in spread_df.columns:
        filtered_spreads = spread_df[spread_df["Cost_Num"] <= max_budget].drop(
            columns=["Cost_Num", "RR_Num"]
        )
        if not filtered_spreads.empty:
            st.dataframe(filtered_spreads, use_container_width=True, hide_index=True)
        else:
            st.warning(f"在單注預算 ${max_budget} 內，暫無符合 RR ≥ 1:{min_rr_ratio} 的期權組合。")
    else:
        st.warning(f"未找到符合盈虧比 ≥ 1:{min_rr_ratio} 且通過盤中動量過濾的期權組合。")

    st.markdown("### 📋 技術形態候選池")
    if not cand_df.empty:
        st.dataframe(cand_df, use_container_width=True, hide_index=True)
    else:
        st.info("當前暫無符合條件的技術形態標的。")

# 頁尾版本標記
st.markdown("---")
st.markdown(
    f"<div style='text-align: center; font-size: 11px; color: #64748b; font-family: monospace;'>"
    f"OptionsQuant Pro Engine · Release {APP_VERSION} ({BUILD_DATE}) · Risk Defined Vertical Spreads Strategy"
    f"</div>",
    unsafe_allow_html=True,
)
