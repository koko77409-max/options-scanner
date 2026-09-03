from datetime import datetime
import warnings
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

APP_VERSION = "v2.9.3"
BUILD_DATE = "2026-09-03"
BUILD_TAG = "Full Pipeline Scan & Lossless UOA Signal Capture"

warnings.filterwarnings("ignore")

st.set_page_config(
    page_title=f"美股期權量化埋伏信號板 ({APP_VERSION})",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
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
</style>
""",
    unsafe_allow_html=True,
)

st.sidebar.title("⚙️ 參數設定")
st.sidebar.markdown(f"系統核心版本：`{APP_VERSION}`")

dte_min, dte_max = st.sidebar.slider("到期日範圍 (DTE)", 14, 60, (20, 45))
atr_multiplier = st.sidebar.slider("通道 ATR 倍數", 1.2, 2.5, 1.8, 0.1)
max_budget = st.sidebar.number_input("單注最大預算 ($)", 20, 2000, 350, 50)
min_rr_ratio = st.sidebar.slider("🔥 最低盈虧比 (1 : X)", 1.0, 3.0, 1.3, 0.1)

st.sidebar.markdown("### 🚨 異動 (UOA) 門檻")
min_uoa_vol = st.sidebar.number_input("異動最小成交量 (張)", 100, 10000, 800, 100)
min_vol_oi_ratio = st.sidebar.slider("Vol / OI 倍數", 1.5, 10.0, 2.5, 0.5)

st.sidebar.markdown("### 🛡️ 全自動風控")
avoid_earnings = st.sidebar.checkbox("自動避開 7 天內財報", value=True)
filter_liquidity = st.sidebar.checkbox("自動過濾寬點差合約", value=True)

st.sidebar.markdown("### 🎯 止盈止損比例")
tp_ratio_min = st.sidebar.slider("最小止盈比率 (%)", 30, 80, 50) / 100.0
tp_ratio_max = st.sidebar.slider("理想止盈比率 (%)", 50, 90, 70) / 100.0
sl_ratio = st.sidebar.slider("剛性止損比率 (%)", 20, 60, 40) / 100.0

st.sidebar.markdown("---")
st.sidebar.caption(f"構建版本：`{APP_VERSION}` | `{BUILD_DATE}`")

col_title, col_ver = st.columns([4, 1])
with col_title:
    st.markdown(
        f"## ⚡ 美股期權量化埋伏信號板 <span class='version-badge'>{APP_VERSION}</span>",
        unsafe_allow_html=True,
    )
    st.caption("直接顯示：到期日、買入價位、賣出價位、限價單價格與止盈止損目標")
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

def check_earnings_risk(ticker_obj):
    try:
        cal = ticker_obj.calendar
        if cal is None or (isinstance(cal, pd.DataFrame) and cal.empty):
            return False
        earnings_date = None
        if isinstance(cal, pd.DataFrame):
            if "Earnings Date" in cal.index:
                earnings_date = cal.loc["Earnings Date"].iloc[0]
        elif isinstance(cal, dict):
            if "Earnings Date" in cal and len(cal["Earnings Date"]) > 0:
                earnings_date = cal["Earnings Date"][0]
        if earnings_date:
            if isinstance(earnings_date, str):
                earnings_date = datetime.strptime(earnings_date[:10], "%Y-%m-%d").date()
            elif hasattr(earnings_date, "date"):
                earnings_date = earnings_date.date()
            days_to_earnings = (earnings_date - datetime.today().date()).days
            if 0 <= days_to_earnings <= 7:
                return True
    except Exception:
        pass
    return False

def run_scan(tickers, atr_mult, filter_earnings):
    candidates = []
    for sym in tickers:
        try:
            t_obj = yf.Ticker(sym)
            if filter_earnings and check_earnings_risk(t_obj):
                continue

            df = t_obj.history(period="6mo", interval="1d")
            if df.empty or len(df) < 30:
                continue

            close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"]

            ma20 = close.rolling(20).mean()
            std20 = close.rolling(20).std()
            bb_upper = ma20 + (2 * std20)
            bb_lower = ma20 - (2 * std20)

            ema8 = close.ewm(span=8, adjust=False).mean()
            ema21 = close.ewm(span=21, adjust=False).mean()

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
            curr_ma20 = float(ma20.iloc[-1])
            curr_ema8 = float(ema8.iloc[-1])
            curr_ema21 = float(ema21.iloc[-1])

            is_bullish = (curr_ema8 >= curr_ema21) and (curr_close >= curr_ma20 * 0.990)
            is_bearish = (curr_ema8 < curr_ema21) and (curr_close <= curr_ma20 * 1.010)

            if not is_bullish and not is_bearish:
                continue

            bb_w = bb_upper.iloc[-1] - bb_lower.iloc[-1]
            kc_w = kc_upper.iloc[-1] - kc_lower.iloc[-1]
            comp_ratio = round(float(bb_w / kc_w), 2) if kc_w > 0 else 1.0

            if recent_squeeze or comp_ratio < 1.10:
                candidates.append({
                    "Symbol": sym,
                    "Direction": "多頭 (CALL)" if is_bullish else "空頭 (PUT)",
                    "Price": round(curr_close, 2),
                    "20MA": round(curr_ma20, 2),
                    "EMA8/21": "多頭排列" if is_bullish else "空頭排列",
                    "壓縮比率": comp_ratio,
                    "Squeeze現狀": bool(is_squeezing.iloc[-1]),
                })
        except Exception:
            continue

    if not candidates:
        return pd.DataFrame(columns=["Symbol", "Direction", "Price", "20MA", "EMA8/21", "壓縮比率", "Squeeze現狀"])
    return pd.DataFrame(candidates)

def get_options_spreads_and_uoa(candidates_df, d_min, d_max, tp_min_pct, tp_max_pct, sl_pct, min_rr, check_liq, min_vol, min_ratio):
    spreads_columns = [
        "標的代號", "方向", "正股現價", "到期日", "策略", "【買入行使價】",
        "【賣出行使價】", "開倉限價 (單價)", "單手成本 ($)", "目標止盈限價", "剛性止損價位", "盈虧比", "Cost_Num", "RR_Num"
    ]
    uoa_columns = ["標的代號", "類型", "到期日", "異動行使價", "合約市價", "成交量", "未平倉 (OI)", "Vol/OI 倍數"]

    if candidates_df.empty:
        return pd.DataFrame(columns=spreads_columns), pd.DataFrame(columns=uoa_columns)

    today = datetime.today()
    spreads = []
    uoa_alerts = []

    # 完整掃描所有技術候選標的
    for _, row in candidates_df.iterrows():
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

            # 1. 異動掃描 (UOA)
            calls_df = chain.calls.copy()
            if not calls_df.empty:
                for _, c_row in calls_df.iterrows():
                    c_vol = c_row.get("volume", 0)
                    c_oi = c_row.get("openInterest", 0)
                    if pd.isna(c_vol) or pd.isna(c_oi) or c_oi == 0:
                        continue
                    c_ratio = round(float(c_vol) / float(c_oi), 2)
                    if c_vol >= min_vol and c_ratio >= min_ratio:
                        uoa_alerts.append({
                            "標的代號": sym,
                            "類型": "🔥 CALL 異動掃盤",
                            "到期日": f"{target_exp} ({target_dte}天)",
                            "異動行使價": f"${c_row.get('strike')} Call",
                            "合約市價": f"${round(float(c_row.get('lastPrice', 0.0)), 2)}",
                            "成交量": int(c_vol),
                            "未平倉 (OI)": int(c_oi),
                            "Vol/OI 倍數": f"{c_ratio}x"
                        })

            # 2. 垂直價差生成
            if "CALL" in direction:
                calls = chain.calls.copy()
                if calls.empty:
                    continue
                calls = calls.sort_values("strike", ascending=True)

                b_cands = calls[calls["strike"] >= curr_price * 0.99]
                s_cands = calls[calls["strike"] >= curr_price * 1.02]
                if b_cands.empty or s_cands.empty:
                    continue

                b_leg = b_cands.iloc[0]
                s_valid = s_cands[s_cands["strike"] > b_leg["strike"]]
                if s_valid.empty:
                    continue
                s_leg = s_valid.iloc[0]

                if check_liq:
                    b_bid, b_ask = float(b_leg.get("bid", 0)), float(b_leg.get("ask", 0))
                    s_bid, s_ask = float(s_leg.get("bid", 0)), float(s_leg.get("ask", 0))
                    if b_ask <= 0 or s_bid <= 0:
                        continue
                    if (b_ask - b_bid) > 0.45 or (s_ask - s_bid) > 0.45:
                        continue

                b_p = float(b_leg["ask"]) if float(b_leg["ask"]) > 0 else float(b_leg["lastPrice"])
                s_p = float(s_leg["bid"]) if float(s_leg["bid"]) > 0 else (float(s_leg["lastPrice"]) if float(s_leg["lastPrice"]) < b_p else 0.0)

                net_debit = max(0.05, round(b_p - s_p, 2))
                cost = round(net_debit * 100, 2)
                spread_width = float(s_leg["strike"]) - float(b_leg["strike"])
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
                sl_price = round(net_debit * (1 - sl_pct), 2)

                spreads.append({
                    "標的代號": sym,
                    "方向": "🟢 多 (Call)",
                    "正股現價": f"${curr_price}",
                    "到期日": f"{target_exp} ({target_dte}天)",
                    "策略": "Bull Call Spread",
                    "【買入行使價】": f"${b_leg['strike']} Call",
                    "【賣出行使價】": f"${s_leg['strike']} Call",
                    "開倉限價 (單價)": f"${net_debit}",
                    "單手成本 ($)": f"${cost}",
                    "目標止盈限價": f"${target_close_price_min} ~ ${target_close_price_max}",
                    "剛性止損價位": f"${sl_price} (-40%)",
                    "盈虧比": f"1 : {rr}",
                    "Cost_Num": cost,
                    "RR_Num": rr,
                })
            else:
                puts = chain.puts.copy()
                if puts.empty:
                    continue
                puts = puts.sort_values("strike", ascending=True)

                b_cands = puts[puts["strike"] <= curr_price * 1.01]
                s_cands = puts[puts["strike"] <= curr_price * 0.98]
                if b_cands.empty or s_cands.empty:
                    continue

                b_leg = b_cands.iloc[-1]
                s_valid = s_cands[s_cands["strike"] < b_leg["strike"]]
                if s_valid.empty:
                    continue
                s_leg = s_valid.iloc[-1]

                if check_liq:
                    b_bid, b_ask = float(b_leg.get("bid", 0)), float(b_leg.get("ask", 0))
                    s_bid, s_ask = float(s_leg.get("bid", 0)), float(s_leg.get("ask", 0))
                    if b_ask <= 0 or s_bid <= 0:
                        continue
                    if (b_ask - b_bid) > 0.45 or (s_ask - s_bid) > 0.45:
                        continue

                b_p = float(b_leg["ask"]) if float(b_leg["ask"]) > 0 else float(b_leg["lastPrice"])
                s_p = float(s_leg["bid"]) if float(s_leg["bid"]) > 0 else (float(s_leg["lastPrice"]) if float(s_leg["lastPrice"]) < b_p else 0.0)

                net_debit = max(0.05, round(b_p - s_p, 2))
                cost = round(net_debit * 100, 2)
                spread_width = float(b_leg["strike"]) - float(s_leg["strike"])
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
                sl_price = round(net_debit * (1 - sl_pct), 2)

                spreads.append({
                    "標的代號": sym,
                    "方向": "🔴 空 (Put)",
                    "正股現價": f"${curr_price}",
                    "到期日": f"{target_exp} ({target_dte}天)",
                    "策略": "Bear Put Spread",
                    "【買入行使價】": f"${b_leg['strike']} Put",
                    "【賣出行使價】": f"${s_leg['strike']} Put",
                    "開倉限價 (單價)": f"${net_debit}",
                    "單手成本 ($)": f"${cost}",
                    "目標止盈限價": f"${target_close_price_min} ~ ${target_close_price_max}",
                    "剛性止損價位": f"${sl_price} (-40%)",
                    "盈虧比": f"1 : {rr}",
                    "Cost_Num": cost,
                    "RR_Num": rr,
                })
        except Exception:
            continue

    df_spreads = pd.DataFrame(spreads)
    if not df_spreads.empty:
        df_spreads = df_spreads.sort_values(by="RR_Num", ascending=False)
    else:
        df_spreads = pd.DataFrame(columns=spreads_columns)

    df_uoa = pd.DataFrame(uoa_alerts)
    if df_uoa.empty:
        df_uoa = pd.DataFrame(columns=uoa_columns)

    return df_spreads, df_uoa

if st.button("🚀 開始全市場量化埋伏與主力異動掃描"):
    with st.spinner("正在掃描全量候選標的之期權鏈與 UOA 異動..."):
        cand_df = run_scan(DEFAULT_WATCHLIST, atr_multiplier, avoid_earnings)
        st.session_state["cand_df"] = cand_df
        spread_df, uoa_df = get_options_spreads_and_uoa(
            cand_df, dte_min, dte_max, tp_ratio_min, tp_ratio_max, sl_ratio, min_rr_ratio, filter_liquidity, min_uoa_vol, min_vol_oi_ratio
        )
        st.session_state["spread_df"] = spread_df
        st.session_state["uoa_df"] = uoa_df

if "cand_df" in st.session_state and "spread_df" in st.session_state and "uoa_df" in st.session_state:
    cand_df = st.session_state["cand_df"]
    spread_df = st.session_state["spread_df"]
    uoa_df = st.session_state["uoa_df"]

    squeeze_count = len(cand_df[cand_df["Squeeze現狀"]]) if not cand_df.empty and "Squeeze現狀" in cand_df.columns else 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("掃描標的池", f"{len(DEFAULT_WATCHLIST)} 隻")
    col2.metric("Squeeze 蓄勢中", f"{squeeze_count} 隻")
    col3.metric("推薦開倉組合", f"{len(spread_df)} 組")
    col4.metric("🚨 主力異動", f"{len(uoa_df)} 個合約")

    st.markdown(f"### 🎯 推薦期權買入指令板 (直接對照買入)")
    if not spread_df.empty and "Cost_Num" in spread_df.columns:
        filtered_spreads = spread_df[spread_df["Cost_Num"] <= max_budget]
        display_df = filtered_spreads.drop(columns=["Cost_Num", "RR_Num"])
        if not display_df.empty:
            st.dataframe(display_df, use_container_width=True, hide_index=True)
        else:
            st.warning(f"在單注預算 ${max_budget} 內，暫無符合門檻的價差組合。")
    else:
        st.warning("未找到符合條件且避開財報的價差組合。")

    st.markdown("### 🚨 期權異常異動雷達 (知情資金爆量掃盤)")
    if not uoa_df.empty:
        st.dataframe(uoa_df, use_container_width=True, hide_index=True)
    else:
        st.info("當前候選池標的未錄得異常異動大單。")

    st.markdown("### 📋 技術形態候選池 (Squeeze 壓縮狀態)")
    if not cand_df.empty:
        st.dataframe(cand_df, use_container_width=True, hide_index=True)
    else:
        st.info("當前暫無符合條件的技術形態標的。")

st.markdown("---")
st.markdown(
    f"<div style='text-align: center; font-size: 11px; color: #64748b; font-family: monospace;'>"
    f"OptionsQuant Pro Engine · Release {APP_VERSION} ({BUILD_DATE}) · Clean Signal Board"
    f"</div>",
    unsafe_allow_html=True,
)
