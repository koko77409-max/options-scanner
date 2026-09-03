import os
import time
import warnings
from datetime import datetime
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

# ==========================================
# 版本號定義
# ==========================================
APP_VERSION = "v3.4.4"
BUILD_DATE = "2026-09-03"
BUILD_TAG = "Fixed Delayed Bid/Ask Misclassification + 5-Min Hardcoded Cruise"
LOG_FILE = "trade_log.csv"
AUTO_SCAN_INTERVAL_SEC = 300  # 固定寫死 5 分鐘 (300 秒)

warnings.filterwarnings("ignore")

st.set_page_config(
    page_title=f"美股期權主力資金流追蹤終端 ({APP_VERSION})",
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

st.sidebar.title("⚙️ 主力資金雷達參數")
st.sidebar.markdown(f"系統核心版本：`{APP_VERSION}`")

# ⏱️ 定時自動巡航開關（固定 5 分鐘）
st.sidebar.markdown("### ⏱️ 定時自動巡航")
auto_scan_enabled = st.sidebar.checkbox("開啟 5 分鐘定時自動巡航", value=True)

dte_min, dte_max = st.sidebar.slider("到期日範圍 (DTE)", 14, 60, (20, 45))
max_budget = st.sidebar.number_input("小資金單注最大預算 ($)", 20, 2000, 350, 50)
min_rr_ratio = st.sidebar.slider("🔥 價差最低盈虧比 (1 : X)", 1.0, 3.0, 1.3, 0.1)

st.sidebar.markdown("### 🚨 知情資金 (UOA) 爆量門檻")
min_uoa_vol = st.sidebar.number_input("合約最小成交量 (張)", 100, 10000, 500, 100)
min_vol_oi_ratio = st.sidebar.slider("Vol / OI 放大倍數", 1.5, 10.0, 2.0, 0.5)
min_notional_usd = st.sidebar.number_input(
    "大單權利金總體量 ($)", 10000, 1000000, 150000, 25000
)

st.sidebar.markdown("### 🛡️ 主力動能硬防護 (防陰跌砸盤)")
min_contract_gain_pct = st.sidebar.slider(
    "🔥 合約當日最低漲幅 (%)", 0, 50, 10, 5
)
avoid_earnings = st.sidebar.checkbox(
    "自動剔除 7 天內即將公布財報標的", value=True
)

st.sidebar.markdown("---")
st.sidebar.caption(
    f"構建版本：`{APP_VERSION}` | `{BUILD_DATE}`\n\n特性：`{BUILD_TAG}`"
)

col_title, col_ver = st.columns([4, 1])
with col_title:
  st.markdown(
      f"## ⚡ 美股期權主力資金流追蹤終端"
      f" <span class='version-badge'>{APP_VERSION}</span>",
      unsafe_allow_html=True,
  )
  st.caption("抗數據延遲誤殺 · 5分鐘固定巡航 · 自動寫入 CSV 紀錄 · OTM 15% 容限")
with col_ver:
  st.markdown(
      f"<div style='text-align:right; font-size:12px;"
      f" color:#94a3b8;'>核心架構：<br><strong style='color:#e2e8f0;'>Release"
      f" {APP_VERSION}</strong></div>",
      unsafe_allow_html=True,
  )

SECTOR_MAP = {
    "SPY": "大盤 ETF",
    "QQQ": "大盤 ETF",
    "IWM": "大盤 ETF",
    "SOXL": "半導體槓桿",
    "NVDA": "半導體/AI",
    "TSLA": "新能源車",
    "AAPL": "消費電子",
    "MSFT": "雲端/AI",
    "AMZN": "電商/雲端",
    "META": "社交/廣告",
    "GOOGL": "搜尋/雲端",
    "AMD": "半導體/AI",
    "AVGO": "半導體/AI",
    "TSM": "半導體/AI",
    "QCOM": "半導體/AI",
    "ASML": "半導體/AI",
    "MU": "半導體/AI",
    "ARM": "半導體/AI",
    "INTC": "半導體/AI",
    "SMCI": "半導體/AI",
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
    "COIN": "加密貨幣",
    "MSTR": "加密貨幣",
    "MARA": "加密貨幣",
    "HOOD": "金融科技",
    "AFRM": "金融科技",
    "SOFI": "金融科技",
    "UPST": "金融科技",
    "UBER": "移動出行",
    "DIS": "娛樂傳媒",
    "NFLX": "串流媒體",
    "RBLX": "元宇宙/遊戲",
    "DKNG": "在線博彩",
    "COST": "消費零售",
    "WMT": "消費零售",
    "BABA": "中概互聯",
    "PDD": "中概互聯",
    "JD": "中概互聯",
    "NIO": "中概互聯",
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


def save_to_log(df_records):
  if df_records.empty:
    return
  now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  records = df_records.copy()
  records.insert(0, "記錄時間", now_str)

  if not os.path.exists(LOG_FILE):
    records.to_csv(LOG_FILE, index=False, encoding="utf-8-sig")
  else:
    existing = pd.read_csv(LOG_FILE, encoding="utf-8-sig")
    combined = pd.concat([records, existing], ignore_index=True).drop_duplicates(
        subset=["標的代號", "異動行使價", "到期日", "合約當日漲跌"]
    )
    combined.to_csv(LOG_FILE, index=False, encoding="utf-8-sig")


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


def scan_pure_flow(
    tickers,
    d_min,
    d_max,
    min_uoa_v,
    min_uoa_r,
    budget,
    min_rr,
    avoid_earn,
    min_notional,
    min_gain_pct,
):
  today = datetime.today()
  uoa_alerts = []
  spread_recommendations = []

  for sym in tickers:
    try:
      t_obj = yf.Ticker(sym)
      if avoid_earn and check_earnings_risk(t_obj):
        continue

      fast_info = t_obj.fast_info
      curr_price = float(
          fast_info.last_price
          if hasattr(fast_info, "last_price") and fast_info.last_price
          else 0
      )
      if curr_price <= 0:
        h = t_obj.history(period="5d")
        if h.empty:
          continue
        curr_price = float(h["Close"].iloc[-1])

      expirations = t_obj.options
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

      chain = t_obj.option_chain(target_exp)

      # ---------------- 1. 看漲 Call 掃描 ----------------
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
            c_bid = float(c_row.get("bid", 0.0))
            c_ask = float(c_row.get("ask", 0.0))
            c_pct_change = float(c_row.get("percentChange", 0.0))
            if pd.isna(c_pct_change):
              c_pct_change = 0.0

            cost_total = round(c_price * 100, 1)
            notional_usd = round(c_price * c_vol * 100, 1)

            mid_price = (
                (c_bid + c_ask) / 2.0 if (c_bid > 0 and c_ask > 0) else c_price
            )
            # 🔥 抗延遲買盤判定：漲幅達標直接確認為主動推升，不再被過期 Bid/Ask 誤殺
            is_buyer_initiated = (
                True
                if c_pct_change >= min_gain_pct
                else (
                    (c_price >= mid_price * 0.98) if mid_price > 0 else True
                )
            )
            otm_pct = (
                (c_strike - curr_price) / curr_price if curr_price > 0 else 0.0
            )

            if c_pct_change < min_gain_pct:
              rec_badge = "🔴 嚴禁買入"
              reason = (
                  f"合約動能失真 ({round(c_pct_change, 1)}%)，未達最低暴增漲幅"
                  f" (+{min_gain_pct}%)，屬陰跌拋售"
              )
              tp_target, sl_target = "不適用", "不適用"
            elif not is_buyer_initiated:
              rec_badge = "🔴 嚴禁買入"
              reason = (
                  "主力主動砸盤平倉 (打在 Bid 價附近)，非買盤進場"
              )
              tp_target, sl_target = "不適用", "不適用"
            elif notional_usd < min_notional:
              rec_badge = "⚠️ 暫不推薦"
              reason = (
                  f"大單總額 ${int(notional_usd):,} 未達主力資金門檻"
                  f" (${int(min_notional):,})"
              )
              tp_target, sl_target = "不適用", "不適用"
            elif otm_pct > 0.15:
              rec_badge = "🔴 嚴禁買入"
              reason = (
                  f"深度虛值 (+{round(otm_pct*100, 1)}%)，彩票陷阱 /"
                  " 機構賣出腿"
              )
              tp_target, sl_target = "不適用", "不適用"
            elif cost_total > budget:
              rec_badge = "⚠️ 暫不推薦"
              reason = f"單手成本 ${cost_total} 超出單注預算 (${budget})"
              tp_target, sl_target = "不適用", "不適用"
            else:
              rec_badge = "🟢 建議買入"
              reason = (
                  f"主動追價掃盤 (漲幅 +{round(c_pct_change, 1)}%)，總額"
                  f" ${int(notional_usd):,}，主力動能極強"
              )
              tp_target = (
                  f"${round(c_price * 1.6, 2)} ~ ${round(c_price * 1.8, 2)}"
              )
              sl_target = f"${round(c_price * 0.65, 2)}"

              s_cands = calls_df[calls_df["strike"] > c_strike]
              if not s_cands.empty:
                s_leg = s_cands.iloc[0]
                b_p = c_price
                s_p = (
                    float(s_leg.get("bid", 0))
                    if float(s_leg.get("bid", 0)) > 0
                    else float(s_leg.get("lastPrice", 0))
                )
                net_debit = max(0.05, round(b_p - s_p, 2))
                cost = round(net_debit * 100, 2)
                spread_width = float(s_leg["strike"]) - c_strike
                max_profit = round((spread_width * 100) - cost, 2)
                rr = round(max_profit / cost, 2) if cost > 0 else 0

                if rr >= min_rr and cost <= budget:
                  spread_recommendations.append({
                      "標的代號": sym,
                      "板塊": SECTOR_MAP.get(sym, "其他"),
                      "方向": "🟢 跟隨做多 (Call)",
                      "正股現價": f"${round(curr_price, 2)}",
                      "到期日": f"{target_exp} ({target_dte}天)",
                      "策略": "Bull Call Spread",
                      "【買入行使價】": f"${c_strike} Call",
                      "【賣出行使價】": f"${s_leg['strike']} Call",
                      "開倉限價 (單價)": f"${net_debit}",
                      "單手成本 ($)": f"${cost}",
                      "目標止盈限價": (
                          f"${round(net_debit + (max_profit*0.5/100), 2)} ~"
                          f" ${round(net_debit + (max_profit*0.7/100), 2)}"
                      ),
                      "剛性止損價位": f"${round(net_debit * 0.6, 2)} (-40%)",
                      "盈虧比": f"1 : {rr}",
                      "Cost_Num": cost,
                      "RR_Num": rr,
                  })

            uoa_alerts.append({
                "推薦評級": rec_badge,
                "標的代號": sym,
                "方向類型": "🟢 看漲 (Call 異動)",
                "合約當日漲跌": (
                    f"{'+' if c_pct_change>0 else ''}{round(c_pct_change, 1)}%"
                ),
                "到期日": f"{target_exp} ({target_dte}天)",
                "異動行使價": f"${c_strike} Call",
                "單張成本 ($)": f"${cost_total}",
                "大單成交額 ($)": f"${int(notional_usd):,}",
                "建議買入限價": f"${c_price}",
                "止盈目標 (+60%)": tp_target,
                "止損底線 (-35%)": sl_target,
                "成交量 / OI (倍數)": (
                    f"{int(c_vol)} / {int(c_oi)} ({c_ratio}x)"
                ),
                "系統判定理由": reason,
            })

      # ---------------- 2. 看跌 Put 掃描 ----------------
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
            p_bid = float(p_row.get("bid", 0.0))
            p_ask = float(p_row.get("ask", 0.0))
            p_pct_change = float(p_row.get("percentChange", 0.0))
            if pd.isna(p_pct_change):
              p_pct_change = 0.0

            cost_total = round(p_price * 100, 1)
            notional_usd = round(p_price * p_vol * 100, 1)

            mid_price = (
                (p_bid + p_ask) / 2.0 if (p_bid > 0 and p_ask > 0) else p_price
            )
            # 🔥 抗延遲買盤判定：做空合約漲幅達標直接確認為買入 Put
            is_buyer_initiated = (
                True
                if p_pct_change >= min_gain_pct
                else (
                    (p_price >= mid_price * 0.98) if mid_price > 0 else True
                )
            )
            otm_pct = (
                (curr_price - p_strike) / curr_price if curr_price > 0 else 0.0
            )

            if p_pct_change < min_gain_pct:
              rec_badge = "🔴 嚴禁買入"
              reason = (
                  f"合約動能失真 ({round(p_pct_change, 1)}%)，未達最低暴增漲幅"
                  f" (+{min_gain_pct}%)，屬陰跌出貨"
              )
              tp_target, sl_target = "不適用", "不適用"
            elif not is_buyer_initiated:
              rec_badge = "🔴 嚴禁買入"
              reason = "主力平倉看跌期權 (打在 Bid 價)，非做空下注"
              tp_target, sl_target = "不適用", "不適用"
            elif notional_usd < min_notional:
              rec_badge = "⚠️ 暫不推薦"
              reason = (
                  f"大單總額 ${int(notional_usd):,} 未達主力資金門檻"
                  f" (${int(min_notional):,})"
              )
              tp_target, sl_target = "不適用", "不適用"
            elif otm_pct > 0.15:
              rec_badge = "🔴 嚴禁買入"
              reason = (
                  f"深度虛值 Put (-{round(otm_pct*100, 1)}%)，彩票對沖 /"
                  " 機構賣出腿"
              )
              tp_target, sl_target = "不適用", "不適用"
            elif cost_total > budget:
              rec_badge = "⚠️ 暫不推薦"
              reason = f"單手成本 ${cost_total} 超出單注預算 (${budget})"
              tp_target, sl_target = "不適用", "不適用"
            else:
              rec_badge = "🟢 建議買入"
              reason = (
                  f"主動追價做空 (漲幅 +{round(p_pct_change, 1)}%)，總額"
                  f" ${int(notional_usd):,}，主力爆量押注大跌"
              )
              tp_target = (
                  f"${round(p_price * 1.6, 2)} ~ ${round(p_price * 1.8, 2)}"
              )
              sl_target = f"${round(p_price * 0.65, 2)}"

              s_cands = puts_df[puts_df["strike"] < p_strike]
              if not s_cands.empty:
                s_leg = s_cands.iloc[-1]
                b_p = p_price
                s_p = (
                    float(s_leg.get("bid", 0))
                    if float(s_leg.get("bid", 0)) > 0
                    else float(s_leg.get("lastPrice", 0))
                )
                net_debit = max(0.05, round(b_p - s_p, 2))
                cost = round(net_debit * 100, 2)
                spread_width = p_strike - float(s_leg["strike"])
                max_profit = round((spread_width * 100) - cost, 2)
                rr = round(max_profit / cost, 2) if cost > 0 else 0

                if rr >= min_rr and cost <= budget:
                  spread_recommendations.append({
                      "標的代號": sym,
                      "板塊": SECTOR_MAP.get(sym, "其他"),
                      "方向": "🔴 跟隨做空 (Put)",
                      "正股現價": f"${round(curr_price, 2)}",
                      "到期日": f"{target_exp} ({target_dte}天)",
                      "策略": "Bear Put Spread",
                      "【買入行使價】": f"${p_strike} Put",
                      "【賣出行使價】": f"${s_leg['strike']} Put",
                      "開倉限價 (單價)": f"${net_debit}",
                      "單手成本 ($)": f"${cost}",
                      "目標止盈限價": (
                          f"${round(net_debit + (max_profit*0.5/100), 2)} ~"
                          f" ${round(net_debit + (max_profit*0.7/100), 2)}"
                      ),
                      "剛性止損價位": f"${round(net_debit * 0.6, 2)} (-40%)",
                      "盈虧比": f"1 : {rr}",
                      "Cost_Num": cost,
                      "RR_Num": rr,
                  })

            uoa_alerts.append({
                "推薦評級": rec_badge,
                "標的代號": sym,
                "方向類型": "🔴 做空 (Put 異動)",
                "合約當日漲跌": (
                    f"{'+' if p_pct_change>0 else ''}{round(p_pct_change, 1)}%"
                ),
                "到期日": f"{target_exp} ({target_dte}天)",
                "異動行使價": f"${p_strike} Put",
                "單張成本 ($)": f"${cost_total}",
                "大單成交額 ($)": f"${int(notional_usd):,}",
                "建議買入限價": f"${p_price}",
                "止盈目標 (+60%)": tp_target,
                "止損底線 (-35%)": sl_target,
                "成交量 / OI (倍數)": (
                    f"{int(p_vol)} / {int(p_oi)} ({p_ratio}x)"
                ),
                "系統判定理由": reason,
            })
    except Exception:
      continue

  df_uoa = pd.DataFrame(uoa_alerts)
  if not df_uoa.empty:
    df_uoa["sort_key"] = df_uoa["推薦評級"].apply(
        lambda x: 0 if "建議買入" in x else 1
    )
    df_uoa = df_uoa.sort_values(by="sort_key").drop(columns=["sort_key"])

  df_spreads = pd.DataFrame(spread_recommendations)
  if not df_spreads.empty:
    df_spreads = df_spreads.sort_values(by="RR_Num", ascending=False)

  return df_uoa, df_spreads


# ==========================================
# 核心掃描觸發器
# ==========================================
def run_scan():
  with st.spinner(
      "正在逐一穿透核心資產期權鏈，執行動能爆發與大單金額算法過濾..."
  ):
    uoa_df, spread_df = scan_pure_flow(
        DEFAULT_WATCHLIST,
        dte_min,
        dte_max,
        min_uoa_vol,
        min_vol_oi_ratio,
        max_budget,
        min_rr_ratio,
        avoid_earnings,
        min_notional_usd,
        min_contract_gain_pct,
    )
    st.session_state["pure_uoa_df"] = uoa_df
    st.session_state["pure_spread_df"] = spread_df

    # 🔥 自動記錄「🟢 建議買入」標的
    if not uoa_df.empty:
      rec_buys = uoa_df[uoa_df["推薦評級"].str.contains("建議買入")].copy()
      if not rec_buys.empty:
        save_to_log(rec_buys)
        st.toast(
            f"✅ 成功將 {len(rec_buys)} 個「建議買入」合約寫入本地歷史紀錄！",
            icon="📝",
        )


# 手動觸發按鈕
if st.button("🚀 開始全市場主力資金流 (UOA) 穿透掃描"):
  run_scan()

# 自動巡航初次啟動
if auto_scan_enabled and "pure_uoa_df" not in st.session_state:
  run_scan()

if "pure_uoa_df" in st.session_state and "pure_spread_df" in st.session_state:
  uoa_df = st.session_state["pure_uoa_df"]
  spread_df = st.session_state["pure_spread_df"]

  rec_count = (
      len(uoa_df[uoa_df["推薦評級"].str.contains("建議買入")])
      if not uoa_df.empty
      else 0
  )

  col1, col2, col3 = st.columns(3)
  col1.metric("穿透監控標的", f"{len(DEFAULT_WATCHLIST)} 隻")
  col2.metric("🚨 資金異動合約", f"{len(uoa_df)} 個")
  col3.metric("🟢 真實主動買盤", f"{rec_count} 個")

  st.markdown("### 🚨 知情主力資金異動雷達 (已過濾陰跌與雜質單)")
  if not uoa_df.empty:
    st.dataframe(uoa_df, use_container_width=True, hide_index=True)
  else:
    st.info("當前篩選門檻下，暫未監測到突破閾值的爆量大單。")

  st.markdown("### 🎯 資金驅動之垂直價差對沖組合 (自動順應主力方向)")
  if not spread_df.empty:
    display_spreads = spread_df.drop(columns=["Cost_Num", "RR_Num"])
    st.dataframe(display_spreads, use_container_width=True, hide_index=True)
  else:
    st.info("暫無符合預算且盈虧比達標的配套價差組合。")

# ==========================================
# 歷史紀錄本 (Trade Log Viewer)
# ==========================================
st.markdown("---")
st.markdown("### 📒 「建議買入」歷史信號紀錄本")

if os.path.exists(LOG_FILE):
  log_data = pd.read_csv(LOG_FILE, encoding="utf-8-sig")
  if not log_data.empty:
    col_dl, col_del = st.columns([4, 1])
    with col_dl:
      csv_data = log_data.to_csv(index=False, encoding="utf-8-sig").encode(
          "utf-8-sig"
      )
      st.download_button(
          label="📥 下載完整歷史交易紀錄 (CSV)",
          data=csv_data,
          file_name=(
              "options_smart_flow_history_"
              f"{datetime.now().strftime('%Y%m%d')}.csv"
          ),
          mime="text/csv",
      )
    st.dataframe(log_data, use_container_width=True, hide_index=True)
  else:
    st.caption("目前暫無歷史紀錄。")
else:
  st.caption(
      "尚未產生任何記錄，當雷達掃描出「🟢 建議買入」標的時會自動寫入。"
  )

st.markdown("---")
st.markdown(
    f"<div style='text-align: center; font-size: 11px; color: #64748b;"
    f" font-family: monospace;'>OptionsQuant Pro Engine · Release {APP_VERSION}"
    f" ({BUILD_DATE}) · Anti-Misclassification Hardened</div>",
    unsafe_allow_html=True,
)

# 🔥 5 分鐘固定自動巡航倒數計時器
if auto_scan_enabled:
  countdown_container = st.empty()
  for remaining in range(AUTO_SCAN_INTERVAL_SEC, 0, -1):
    mins, secs = divmod(remaining, 60)
    countdown_container.info(
        f"⏱️ **5 分鐘定時巡航運行中**：下次自動重新掃描倒數 **{mins:02d}分"
        f" {secs:02d}秒**...（可隨時取消側邊欄勾選）"
    )
    time.sleep(1)
  run_scan()
  st.rerun()
