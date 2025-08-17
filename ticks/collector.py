import shioaji as sj
import json
from common import get_redis
from get_main_contracts import get_main_contracts
from config import API_KEY, SECRET_KEY
# Redis
r = get_redis()

# 永豐 API login（只這裡一次）
api = sj.Shioaji()
api.login(api_key=API_KEY, secret_key=SECRET_KEY)

def on_tick(exchange, tick):
    tick_data = {
        "symbol": tick.code,
        "timestamp": tick.datetime.strftime("%Y-%m-%d %H:%M:%S"),
        "open": float(tick.open),
        "high": float(tick.high),
        "low": float(tick.low),
        "close": float(tick.close),
        "volume": tick.volume,
        "simtrade": tick.simtrade
    }
    print(tick)
    r.lpush(f"ticks:{tick.code}", json.dumps(tick_data))

# 訂閱主力合約
contract = min(
    [
        x for x in api.Contracts.Futures.TXF 
        if x.code[-2:] not in ["R1", "R2"]
    ],
    key=lambda x: x.delivery_date
)
contract2 = min(
    [
        x for x in api.Contracts.Futures.MXF 
        if x.code[-2:] not in ["R1", "R2"]
    ],
    key=lambda x: x.delivery_date
)
# 設置回調函數
api.quote.set_on_tick_fop_v1_callback(on_tick)

# 開始訂閱行情數據
api.quote.subscribe(
    contract=contract,
    quote_type=sj.constant.QuoteType.Tick,  # 訂閱逐筆行情
    version=sj.constant.QuoteVersion.v1    # 使用版本 v1
)
api.quote.subscribe(
    contract=contract2,
    quote_type=sj.constant.QuoteType.Tick,  # 訂閱逐筆行情
    version=sj.constant.QuoteVersion.v1    # 使用版本 v1
)
# api.quote.subscribe(api.Contracts.Futures.TXF[main_txf], quote_type="tick")
# api.quote.subscribe(api.Contracts.Futures.MXF[main_mxf], quote_type="tick")
# api.quote.set_on_tick_stk_v1_callback(on_tick)

print(f"=== Collector 啟動，訂閱 TXF MXF ===")
while True:
    pass
