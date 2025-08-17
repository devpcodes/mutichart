# -*- coding: utf-8 -*-
from datetime import time

# 交易商品清單
SYMBOLS = ["TXF", "MXF"]

# 使用的策略（預設：PSAR 小時K + 即時反轉）
STRATEGY = "sar_psar_hourly"
STRATEGY_PARAMS = {
    "qty": 1,
    # PSAR 參數
    "af": 0.02,        # 加速因子初始值
    "af_max": 0.2,     # 加速因子上限
    # 若你想在 PSAR 外，再加固定停損/移動停利，可擴充以下值（目前不啟用）
    "sl_points": None,
    "trail_points": None,
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
