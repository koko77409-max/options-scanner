import os
import time
import urllib.parse
import urllib.request
import warnings
from datetime import datetime
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ==========================================
# 核心參數配置（與終端標準保持一致）
# ==========================================
BARK_KEY = os.environ.get("BARK_KEY", "vARo3iEDmQv6DbVKM8EW79")
DTE_MIN = 14
DTE_MAX = 45
MAX_BUDGET = 800
MIN_UOA_VOL = 500
MIN_VOL_OI_RATIO = 2.0
MIN_NOTIONAL_USD = 150000
MIN_GAIN_PCT = 10.0
MAX_GAIN_PCT = 150.0  # 防 FOMO 接火棒上限

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
WATCHLIST = list(SECTOR_MAP.keys())


def send_bark_alert(key, title, body, group="UOA_Alerts"):
  if not key or not key.strip():
    return False
  clean_key = key.strip().strip("/")
  params = urllib.parse.urlencode({
      "title": title,
      "body": body,
      "group": group,
      "sound": "bell",
      "icon": "https://img.icons8.com/fluency/96/bullish.png",
  })
  url = f"https://api.day.app/{clean_key}/?{params}"
  try:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
      return resp.status == 200
  except Exception as e:
    print(f"Bark 推送異常: {e}")
    return False


def check_earnings_risk(ticker_obj):
  try:
    cal = ticker_obj.calendar
    if cal is None or (isinstance(cal, pd.DataFrame) and cal.empty):
      return False
    earnings_date = None
    if isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
      earnings_date = cal.loc["Earnings Date"].iloc[0]
    elif (
        isinstance(cal, dict)
        and "Earnings Date" in cal
        and len(cal["Earnings Date"]) > 0
    ):
      earnings_date = cal["Earnings Date"][0]

    if earnings_date:
      if isinstance(earnings_date, str):
        earnings_date = datetime.strptime(
            earnings_date[:10], "%Y-%m-%d"
        ).date()
      elif hasattr(earnings_date, "date"):
        earnings_date = earnings_date.date()
      days_to = (earnings_date - datetime.today().date()).days
      if 0 <= days_to <= 7:
        return True
  except Exception:
    pass
  return False


def run_cron_scan():
  today = datetime.today()
  signals = []
  print(
      f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 開始執行 GitHub"
      f" Actions 後台巡航，監控 {len(WATCHLIST)} 隻標的..."
  )

  for sym in WATCHLIST:
    try:
      time.sleep(0.12)  # 防 429 錯峰
      t_obj = yf.Ticker(sym)
      if check_earnings_risk(t_obj):
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

      target_dates = []
      for exp in expirations:
        dte = (datetime.strptime(exp, "%Y-%m-%d") - today).days
        if DTE_MIN <= dte <= DTE_MAX:
          target_dates.append((exp, dte))
          if len(target_dates) >= 2:
            break

      if not target_dates:
        continue

      for target_exp, target_dte in target_dates:
        try:
          chain = t_obj.option_chain(target_exp)
        except Exception:
          continue

        # 掃描 Call
        calls = chain.calls
        if not calls.empty:
          for _, c_row in calls.iterrows():
            vol = c_row.get("volume", 0)
            oi = c_row.get("openInterest", 0)
            if pd.isna(vol) or pd.isna(oi) or oi == 0:
              continue
            ratio = round(float(vol) / float(oi), 2)
            if vol >= MIN_UOA_VOL and ratio >= MIN_VOL_OI_RATIO:
              strike = float(c_row.get("strike", 0))
              price = float(c_row.get("lastPrice", 0.0))
              pct_chg = float(c_row.get("percentChange", 0.0))
              if pd.isna(pct_chg):
                pct_chg = 0.0

              cost = round(price * 100, 1)
              notional = round(price * vol * 100, 1)
              otm_pct = (
                  (strike - curr_price) / curr_price if curr_price > 0 else 0
              )

              # 嚴格風控門檻判定
              if (
                  MIN_GAIN_PCT <= pct_chg <= MAX_GAIN_PCT
                  and notional >= MIN_NOTIONAL_USD
                  and otm_pct <= 0.15
                  and cost <= MAX_BUDGET
              ):
                short_exp = target_exp[5:].replace("-", "/")
                title = f"🟢 主力買入: {sym} {short_exp} ${strike} Call"
                body = (
                    f"到期日: {target_exp} ({target_dte}天)\n"
                    f"成本: ${cost} | 漲幅: +{round(pct_chg, 1)}%\n"
                    f"限價: ${price} | 體量: ${int(notional):,}\n"
                    f"止盈: ${round(price*1.6, 2)} ~ ${round(price*1.8, 2)} |"
                    f" 止損: ${round(price*0.65, 2)}"
                )
                print(f"🔥 觸發買入信號: {title}")
                send_bark_alert(BARK_KEY, title, body)
                signals.append(title)

        # 掃描 Put
        puts = chain.puts
        if not puts.empty:
          for _, p_row in puts.iterrows():
            vol = p_row.get("volume", 0)
            oi = p_row.get("openInterest", 0)
            if pd.isna(vol) or pd.isna(oi) or oi == 0:
              continue
            ratio = round(float(vol) / float(oi), 2)
            if vol >= MIN_UOA_VOL and ratio >= MIN_VOL_OI_RATIO:
              strike = float(p_row.get("strike", 0))
              price = float(p_row.get("lastPrice", 0.0))
              pct_chg = float(p_row.get("percentChange", 0.0))
              if pd.isna(pct_chg):
                pct_chg = 0.0

              cost = round(price * 100, 1)
              notional = round(price * vol * 100, 1)
              otm_pct = (
                  (curr_price - strike) / curr_price if curr_price > 0 else 0
              )

              if (
                  MIN_GAIN_PCT <= pct_chg <= MAX_GAIN_PCT
                  and notional >= MIN_NOTIONAL_USD
                  and otm_pct <= 0.15
                  and cost <= MAX_BUDGET
              ):
                short_exp = target_exp[5:].replace("-", "/")
                title = f"🔴 主力做空: {sym} {short_exp} ${strike} Put"
                body = (
                    f"到期日: {target_exp} ({target_dte}天)\n"
                    f"成本: ${cost} | 漲幅: +{round(pct_chg, 1)}%\n"
                    f"限價: ${price} | 體量: ${int(notional):,}\n"
                    f"止盈: ${round(price*1.6, 2)} ~ ${round(price*1.8, 2)} |"
                    f" 止損: ${round(price*0.65, 2)}"
                )
                print(f"🔥 觸發做空信號: {title}")
                send_bark_alert(BARK_KEY, title, body)
                signals.append(title)
    except Exception as e:
      continue

  print(f"巡航完成，共推播 {len(signals)} 個符合標準的知情主力信號。")


if __name__ == "__main__":
  run_cron_scan()
