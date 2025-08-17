# -*- coding: utf-8 -*-
from datetime import time
import os
# 交易商品清單
SYMBOLS = ["TXF", "MXF"]

# 使用的策略（預設：PSAR 小時K + 即時反轉）
STRATEGY = "sar_psar_hourly"
STRATEGY_PARAMS = {
    "qty": 1,
    "af": 0.02,
    "af_max": 0.2,
    "sl_points": 200,        # ← 不要 None
    "trail_trigger": 200,    # ← 不要 None
    "trail_retrace": 0.40    # ← 不要 None
}

# 回測：以 1 分鐘 K 近似 tick；決策用 1 小時 K
FEED_FRAME = "1min"
BAR_FRAME  = "1H"

# 期貨乘數（點 → 元）
MULTIPLIER = {"TXF": 200, "MXF": 50}

# MySQL（回測讀資料用）
MYSQL_URL = "mysql+pymysql://trader:traderpass@localhost:3307/market"

# Redis（實盤即時行情）
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB   = 0
REDIS_CHANNEL_PREFIX = "ticks:"

# 台北交易時段（例：日盤；可自行擴充夜盤）
SESSION = [(time(8,45), time(13,45))]

# 每月第三個星期三 13:29 自動平倉
AUTO_CLOSE_ENABLED = True
AUTO_CLOSE_HOUR = 13
AUTO_CLOSE_MINUTE = 29
TIMEZONE = "Asia/Taipei"


# --- Optional: override SESSION by .env ---
from datetime import time as dtime
def _parse_hhmm(s: str):
    s = s.strip()
    if ":" in s: hh, mm = s.split(":", 1)
    else: hh, mm = s[:2], s[2:]
    return int(hh), int(mm or 0)

def _env_session():
    ds = os.getenv("SESSION_DAY_START")
    de = os.getenv("SESSION_DAY_END")
    ns = os.getenv("SESSION_NIGHT_START")
    ne = os.getenv("SESSION_NIGHT_END")
    sess = []
    if ds and de:
        h1, m1 = _parse_hhmm(ds); h2, m2 = _parse_hhmm(de)
        sess.append((dtime(h1, m1), dtime(h2, m2)))
    if ns and ne:
        h1, m1 = _parse_hhmm(ns); h2, m2 = _parse_hhmm(ne)
        sess.append((dtime(h1, m1), dtime(h2, m2)))
    return sess

try:
    _sess_env = _env_session()
    if _sess_env:
        SESSION = _sess_env
except Exception:
    pass
