import warnings
from datetime import datetime
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

# ==========================================
# 版本號定義
# ==========================================
APP_VERSION = "v2.9.6"
BUILD_DATE = "2026-09-03"
BUILD_TAG = (
    "Hardened Quant: Dual-Direction UOA (Call+Put) + Sector Exposure Control"
)

warnings.filterwarnings("ignore")

# 頁面配置
st.set_page_config(
    page_title=f"美股期權量化終端 ({APP_VERSION})",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 樣式自訂
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

# 側邊欄配置
st.sidebar.title("⚙️ 風控與策略設定")
st.sidebar.markdown(f"系統核心版本：`{APP_VERSION}`")

dte_min, dte_max = st.sidebar.slider("期權到期日範圍 (DTE)", 14, 60, (20, 45))
atr_multiplier = st.sidebar.slider("通道 ATR 乘數", 1.2, 2.5, 1.8, 0.1)
max_budget = st.sidebar.number_input("單注最大預算 ($)", 20, 2000, 350, 50)
min_rr_ratio = st.sidebar.slider("🔥 最低盈虧比 (1 : X)", 1.0, 3.0, 1.3, 0.1)

st.sidebar.markdown("### 🚨 雙向異動 (UOA) 門檻")
min_uoa_vol = st.sidebar.number_input(
    "異動最小成交量 (張)", 100, 10000, 800, 100
)
min_vol_oi_ratio = st.sidebar.slider("Vol / OI 放大倍數", 1.5, 10.0, 2.5, 0.5)

st.sidebar.markdown("### 🛡️ 全自動風控模組")
avoid_earnings = st.sidebar.checkbox("自動避開 7 天內財報", value=True)
filter_liquidity = st.sidebar.checkbox("自動過濾寬點差合約", value=True)
limit_sector_risk = st.sidebar.checkbox(
    "啟用板塊防共振 (同一行業最多 2 組)", value=True
)

st.sidebar.markdown("### 🎯 止盈止損比例")
tp_ratio_min = st.sidebar.slider("最小止盈比率 (%)", 30, 80, 50) / 100.0
tp_ratio_max = st.sidebar.slider("理想止盈比率 (%)", 50, 90, 70) / 100.0
sl_ratio = st.sidebar.slider("剛性止損比率 (%)", 20, 60, 40) / 100.0

st.sidebar.markdown("---")
st.sidebar.caption(
    f"構建版本：`{APP_VERSION}` | `{BUILD_DATE}`\n\n特性：`{BUILD_TAG}`"
)

# 頂部標題
col_title, col_ver = st.columns([4, 1])
with col_title:
  st.markdown(
      f"## ⚡ 美股期權量化終端 <span class='version-badge'>{APP_VERSION}</span>",
      unsafe_allow_html=True,
  )
  st.caption(
      "TTM Squeeze 埋伏 + 雙向 UOA (Call多頭/Put做空) 偵測 + 板塊敞口分散防護"
  )
with col_ver:
  st.markdown(
      f"<div style='text-align:right; font-size:12px;"
      f" color:#94a3b8;'>核心引擎：<br><strong style='color:#e2e8f0;'>Release"
      f" {APP_VERSION}</strong></div>",
      unsafe_allow_html=True,
  )

# 板塊分類映射字典（用於板塊去重與集中度風控）
SECTOR_MAP = {
    # 指數
    "SPY": "大盤 ETF",
    "QQQ": "大盤 ETF",
    "IWM": "大盤 ETF",
    "SOXL": "半導體槓桿",
    # 科技巨頭
    "NVDA": "半導體/AI",
    "TSLA": "新能源車",
    "AAPL": "消費電子",
    "MSFT": "雲端/AI",
    "AMZN": "電商/雲端",
    "META": "社交/廣告",
    "GOOGL": "搜尋/雲端",
    # 半導體
    "AMD": "半導體/AI",
    "AVGO": "半導體/AI",
    "TSM": "半導體/AI",
    "QCOM": "半導體/AI",
    "ASML": "半導體/AI",
    "MU": "半導體/AI",
    "ARM": "半導體/AI",
    "INTC": "半導體/AI",
    "SMCI": "半導體/AI",
    # 軟件與網絡安全
    "PLTR": "大數據/AI",
    "CRWD": "網絡安全",
    "PANW": "網絡安全",
    "SNOW": "數據倉庫",
    "NET": "雲端網絡",
    "DDOG": "雲監控",
    "CRM": "企業軟件",
    "ORCL": "企業軟件",
    "SHOP": "電子商務",
    "PATH": "企業軟件",
    # 加密與金融科技
    "COIN": "加密貨幣",
    "MSTR": "加密貨幣",
    "MARA": "加密貨幣",
    "HOOD": "金融科技",
    "AFRM": "金融科技",
    "SOFI": "金融科技",
    "UPST": "金融科技",
    # 消費/零售/移動
    "UBER": "移動出行",
    "DIS": "娛樂傳媒",
    "NFLX": "串流媒體",
    "RBLX": "元宇宙/遊戲",
    "DKNG": "在線博彩",
    "COST": "消費零售",
    "WMT": "消費零售",
    # 中概
    "BABA": "中概互聯",
    "PDD": "中概互聯",
    "JD": "中概互聯",
    "NIO": "中概互聯",
    # 其它
    "RIVN": "新能源車",
    "BA": "航空航天",
    "JPM": "傳統金融",
    "GS": "傳統金融",
    "BAC": "傳統金融",
    "XOM": "傳統能源",
    "CVX": "傳統能源",
    "OXY": "傳統能源",
    "LLY": "醫藥醫療",
    "UNH": "醫藥醫療",
    "CAT": "工業機械",
    "GE": "工業機械",
}

DEFAULT_WATCHLIST = list(SECTOR_MAP.keys())


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
        earnings_date = datetime.strptime(
            earnings_date[:10], "%Y-%m-%d"
        ).date()
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

      is_bullish = (curr_ema8 >= curr_ema21) and (
          curr_close >= curr_ma20 * 0.990
      )
      is_bearish = (curr_ema8 < curr_ema21) and (
          curr_close <= curr_ma20 * 1.010
      )

      if not is_bullish and not is_bearish:
        continue

      bb_w = bb_upper.iloc[-1] - bb_lower.iloc[-1]
      kc_w = kc_upper.iloc[-1] - kc_lower.iloc[-1]
      comp_ratio = round(float(bb_w / kc_w), 2) if kc_w > 0 else 1.0

      if recent_squeeze or comp_ratio < 1.10:
        candidates.append({
            "Symbol": sym,
            "Sector": SECTOR_MAP.get(sym, "其他"),
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
    return pd.DataFrame(
        columns=[
            "Symbol",
            "Sector",
            "Direction",
            "Price",
            "20MA",
            "EMA8/21",
            "壓縮比率",
            "Squeeze現狀",
        ]
    )
  return pd.DataFrame(candidates)


def get_options_spreads_and_uoa(
    candidates_df,
    d_min,
    d_max,
    tp_min_pct,
    tp_max_pct,
    sl_pct,
    min_rr,
    check_liq,
    min_uoa_v,
    min_uoa_r,
    budget,
    enforce_sector_limit,
):
  spreads_columns = [
      "標的代號",
      "板塊",
      "方向",
      "正股現價",
      "到期日",
      "策略",
      "【買入行使價】",
      "【賣出行使價】",
      "開倉限價 (單價)",
      "單手成本 ($)",
      "目標止盈限價",
      "剛性止損價位",
      "盈虧比",
      "Cost_Num",
      "RR_Num",
  ]
  uoa_columns = [
      "推薦評級",
      "標的代號",
      "方向類型",
      "到期日",
      "異動行使價",
      "單張成本 ($)",
      "建議買入限價",
      "止盈目標價 (+60%)",
      "止損底線 (-35%)",
      "成交量 / OI (倍數)",
      "系統判定理由",
  ]

  if candidates_df.empty:
    return pd.DataFrame(columns=spreads_columns), pd.DataFrame(
        columns=uoa_columns
    )

  today = datetime.today()
  spreads = []
  uoa_alerts = []

  for _, row in candidates_df.iterrows():
    sym, curr_price, direction, sector = (
        row["Symbol"],
        row["Price"],
        row["Direction"],
        row["Sector"],
    )
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

      # ---------------- 1. 雙向 UOA 異動分類器 (Calls 多頭 + Puts 空頭) ----------------
      # 1.1 看漲 Call 掃描
      calls_df = chain.calls.copy()
      if not calls_df.empty:
        for _, c_row in calls_df.iterrows():
          c_vol = c_row.get("volume", 0)
          c_oi = c_row.get("openInterest", 0)
          if pd.isna(c_vol) or pd.isna(c_oi) or c_oi == 0:
            continue
          c_ratio = round(float(c_vol) / float(c_oi), 2)

          if c_vol >= min_uoa_v and c_ratio >= min_uoa_r:
            c_strike = float(c_row.get("strike", 0))
            c_price = float(c_row.get("lastPrice", 0.0))
            cost_total = round(c_price * 100, 1)
            otm_pct = (
                (c_strike - curr_price) / curr_price
                if curr_price > 0
                else 0.0
            )

            if otm_pct > 0.12:
              rec_badge = "🔴 嚴禁買入"
              reason = f"深度虛值 (+{round(otm_pct*100, 1)}%)，彩票陷阱 / 機構賣出腿"
              tp_target, sl_target = "不適用", "不適用"
            elif cost_total > budget:
              rec_badge = "⚠️ 暫不推薦"
              reason = f"單手成本 ${cost_total} 超出單注預算 (${budget})"
              tp_target, sl_target = "不適用", "不適用"
            else:
              rec_badge = "🟢 建議買入"
              reason = f"輕度虛值 (+{round(otm_pct*100, 1)}%)，知情大單爆量掃盤，做多性價比極佳"
              tp_target = (
                  f"${round(c_price * 1.6, 2)} ~ ${round(c_price * 1.8, 2)}"
              )
              sl_target = f"${round(c_price * 0.65, 2)}"

            uoa_alerts.append({
                "推薦評級": rec_badge,
                "標的代號": sym,
                "方向類型": "🟢 看漲 (Call 異動)",
                "到期日": f"{target_exp} ({target_dte}天)",
                "異動行使價": f"${c_strike} Call",
                "單張成本 ($)": f"${cost_total}",
                "建議買入限價": f"${c_price}",
                "止盈目標價 (+60%)": tp_target,
                "止損底線 (-35%)": sl_target,
                "成交量 / OI (倍數)": f"{int(c_vol)} / {int(c_oi)} ({c_ratio}x)",
                "系統判定理由": reason,
            })

      # 1.2 看跌 Put 掃描 (防止主力砸盤漏洞)
      puts_df = chain.puts.copy()
      if not puts_df.empty:
        for _, p_row in puts_df.iterrows():
          p_vol = p_row.get("volume", 0)
          p_oi = p_row.get("openInterest", 0)
          if pd.isna(p_vol) or pd.isna(p_oi) or p_oi == 0:
            continue
          p_ratio = round(float(p_vol) / float(p_oi), 2)

          if p_vol >= min_uoa_v and p_ratio >= min_uoa_r:
            p_strike = float(p_row.get("strike", 0))
            p_price = float(p_row.get("lastPrice", 0.0))
            cost_total = round(p_price * 100, 1)
            otm_pct = (
                (curr_price - p_strike) / curr_price
                if curr_price > 0
                else 0.0
            )

            if otm_pct > 0.12:
              rec_badge = "🔴 嚴禁買入"
              reason = f"深度虛值 Put (-{round(otm_pct*100, 1)}%)，彩票對沖 / 賣出腿"
              tp_target, sl_target = "不適用", "不適用"
            elif cost_total > budget:
              rec_badge = "⚠️ 暫不推薦"
              reason = f"單手成本 ${cost_total} 超出單注預算 (${budget})"
              tp_target, sl_target = "不適用", "不適用"
            else:
              rec_badge = "🟢 建議買入"
              reason = f"輕度虛值 (-{round(otm_pct*100, 1)}%)，知情機構巨量押注暴跌，做空性價比極佳"
              tp_target = (
                  f"${round(p_price * 1.6, 2)} ~ ${round(p_price * 1.8, 2)}"
              )
              sl_target = f"${round(p_price * 0.65, 2)}"

            uoa_alerts.append({
                "推薦評級": rec_badge,
                "標的代號": sym,
                "方向類型": "🔴 做空 (Put 異動)",
                "到期日": f"{target_exp} ({target_dte}天)",
                "異動行使價": f"${p_strike} Put",
                "單張成本 ($)": f"${cost_total}",
                "建議買入限價": f"${p_price}",
                "止盈目標價 (+60%)": tp_target,
                "止損底線 (-35%)": sl_target,
                "成交量 / OI (倍數)": f"{int(p_vol)} / {int(p_oi)} ({p_ratio}x)",
                "系統判定理由": reason,
            })

      # ---------------- 2. 垂直價差生成 ----------------
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
          b_bid, b_ask = float(b_leg.get("bid", 0)), float(
              b_leg.get("ask", 0)
          )
          s_bid, s_ask = float(s_leg.get("bid", 0)), float(
              s_leg.get("ask", 0)
          )
          if b_ask <= 0 or s_bid <= 0:
            continue
          if (b_ask - b_bid) > 0.40 or (s_ask - s_bid) > 0.40:
            continue

        b_p = (
            float(b_leg["ask"])
            if float(b_leg["ask"]) > 0
            else float(b_leg["lastPrice"])
        )
        s_p = (
            float(s_leg["bid"])
            if float(s_leg["bid"]) > 0
            else (
                float(s_leg["lastPrice"])
                if float(s_leg["lastPrice"]) < b_p
                else 0.0
            )
        )

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
            "板塊": sector,
            "方向": "🟢 多 (Call)",
            "正股現價": f"${curr_price}",
            "到期日": f"{target_exp} ({target_dte}天)",
            "策略": "Bull Call Spread",
            "【買入行使價】": f"${b_leg['strike']} Call",
            "【賣出行使價】": f"${s_leg['strike']} Call",
            "開倉限價 (單價)": f"${net_debit}",
            "單手成本 ($)": f"${cost}",
            "目標止盈限價": (
                f"${target_close_price_min} ~ ${target_close_price_max}"
            ),
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
          b_bid, b_ask = float(b_leg.get("bid", 0)), float(
              b_leg.get("ask", 0)
          )
          s_bid, s_ask = float(s_leg.get("bid", 0)), float(
              s_leg.get("ask", 0)
          )
          if b_ask <= 0 or s_bid <= 0:
            continue
          if (b_ask - b_bid) > 0.40 or (s_ask - s_bid) > 0.40:
            continue

        b_p = (
            float(b_leg["ask"])
            if float(b_leg["ask"]) > 0
            else float(b_leg["lastPrice"])
        )
        s_p = (
            float(s_leg["bid"])
            if float(s_leg["bid"]) > 0
            else (
                float(s_leg["lastPrice"])
                if float(s_leg["lastPrice"]) < b_p
                else 0.0
            )
        )

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
            "板塊": sector,
            "方向": "🔴 空 (Put)",
            "正股現價": f"${curr_price}",
            "到期日": f"{target_exp} ({target_dte}天)",
            "策略": "Bear Put Spread",
            "【買入行使價】": f"${b_leg['strike']} Put",
            "【賣出行使價】": f"${s_leg['strike']} Put",
            "開倉限價 (單價)": f"${net_debit}",
            "單手成本 ($)": f"${cost}",
            "目標止盈限價": (
                f"${target_close_price_min} ~ ${target_close_price_max}"
            ),
            "剛性止損價位": f"${sl_price} (-40%)",
            "盈虧比": f"1 : {rr}",
            "Cost_Num": cost,
            "RR_Num": rr,
        })
    except Exception:
      continue

  df_spreads = pd.DataFrame(spreads)
  if not df_spreads.empty:
    # 執行板塊敞口防護 (同一板塊最多保留盈虧比最優的 2 個)
    if enforce_sector_limit:
      df_spreads = df_spreads.sort_values(by="RR_Num", ascending=False)
      df_spreads = df_spreads.groupby("板塊").head(2).reset_index(drop=True)
    df_spreads = df_spreads.sort_values(by="RR_Num", ascending=False)
  else:
    df_spreads = pd.DataFrame(columns=spreads_columns)

  df_uoa = pd.DataFrame(uoa_alerts)
  if not df_uoa.empty:
    df_uoa["sort_key"] = df_uoa["推薦評級"].apply(
        lambda x: 0 if "建議買入" in x else 1
    )
    df_uoa = df_uoa.sort_values(by="sort_key").drop(columns=["sort_key"])
  else:
    df_uoa = pd.DataFrame(columns=uoa_columns)

  return df_spreads, df_uoa


if st.button("🚀 開始全市場量化埋伏與主力異動掃描"):
  with st.spinner("正在對 70 隻核心資產執行雙向異動偵測與板塊敞口去重..."):
    cand_df = run_scan(DEFAULT_WATCHLIST, atr_multiplier, avoid_earnings)
    st.session_state["cand_df"] = cand_df
    spread_df, uoa_df = get_options_spreads_and_uoa(
        cand_df,
        dte_min,
        dte_max,
        tp_ratio_min,
        tp_ratio_max,
        sl_ratio,
        min_rr_ratio,
        filter_liquidity,
        min_uoa_vol,
        min_vol_oi_ratio,
        max_budget,
        limit_sector_risk,
    )
    st.session_state["spread_df"] = spread_df
    st.session_state["uoa_df"] = uoa_df

if (
    "cand_df" in st.session_state
    and "spread_df" in st.session_state
    and "uoa_df" in st.session_state
):
  cand_df = st.session_state["cand_df"]
  spread_df = st.session_state["spread_df"]
  uoa_df = st.session_state["uoa_df"]

  squeeze_count = (
      len(cand_df[cand_df["Squeeze現狀"]])
      if not cand_df.empty and "Squeeze現狀" in cand_df.columns
      else 0
  )

  col1, col2, col3, col4 = st.columns(4)
  col1.metric("掃描標的池", f"{len(DEFAULT_WATCHLIST)} 隻")
  col2.metric("Squeeze 蓄勢中", f"{squeeze_count} 隻")
  col3.metric("推薦垂直價差", f"{len(spread_df)} 組")
  col4.metric("🚨 雙向異動", f"{len(uoa_df)} 個合約")

  # 1. 垂直價差組合
  st.markdown(
      f"### 🎯 精選垂直價差指令板 (小資金穩健對沖 · 已過濾板塊集中風險)"
  )
  if not spread_df.empty and "Cost_Num" in spread_df.columns:
    filtered_spreads = spread_df[spread_df["Cost_Num"] <= max_budget]
    display_df = filtered_spreads.drop(columns=["Cost_Num", "RR_Num"])
    if not display_df.empty:
      st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
      st.warning(f"在單注預算 ${max_budget} 內，暫無符合門檻的價差組合。")
  else:
    st.warning("未找到符合條件且避開財報的價差組合。")

  # 2. UOA 主力異動雷達（雙向分類板）
  st.markdown("### 🚨 期權雙向異常異動雷達 (Call多頭 / Put做空 · 智能分類)")
  if not uoa_df.empty:
    st.dataframe(uoa_df, use_container_width=True, hide_index=True)
  else:
    st.info("當前候選池標的未錄得異常異動大單。")

  # 3. 技術形態候選池
  st.markdown("### 📋 技術形態候選池 (Squeeze 壓縮狀態)")
  if not cand_df.empty:
    st.dataframe(cand_df, use_container_width=True, hide_index=True)
  else:
    st.info("當前暫無符合條件的技術形態標的。")

st.markdown("---")
st.markdown(
    f"<div style='text-align: center; font-size: 11px; color: #64748b;"
    f" font-family: monospace;'>OptionsQuant Pro Engine · Release {APP_VERSION}"
    f" ({BUILD_DATE}) · Sector-Hardened Architecture</div>",
    unsafe_allow_html=True,
)
