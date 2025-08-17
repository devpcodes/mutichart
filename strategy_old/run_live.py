# -*- coding: utf-8 -*-
import signal, time
from datetime import datetime, time as dtime
import pytz
from dotenv import load_dotenv
 
from strategy.config import SYMBOLS, STRATEGY, STRATEGY_PARAMS, SESSION, TIMEZONE
from strategy.core.registry import load_strategy
from strategy.core.barbuilder import BarBuilder
from strategy.core.datafeed import RedisTickStream
from strategy.core.calendar import is_third_wed_1329
from strategy.storage.mysql import load_hourly_from_ticks
from strategy.core.events import Bar
from strategy.broker.shioaji_broker import ShioajiBroker
from strategy.logging_setup import setup_logging
setup_logging(app_name="live")
STOP = False
load_dotenv()
def _handle_sig(signum, frame):
    global STOP
    print("\n[SYS] 收到終止訊號，準備優雅關閉...")
    STOP = True

signal.signal(signal.SIGINT, _handle_sig)
signal.signal(signal.SIGTERM, _handle_sig)
tz = pytz.timezone(TIMEZONE)

def in_session(now_local: datetime) -> bool:
    t = now_local.time()
    return any(s <= t <= e for s, e in SESSION)

def _minute_key(ts):
    return ts.replace(second=0, microsecond=0)

def _hour_key(ts):
    return ts.replace(minute=0, second=0, microsecond=0)

def _is_first_minute_open_tick(symbol, ts, seen_dict):
    mk = _minute_key(ts)
    if mk not in seen_dict[symbol]:
        seen_dict[symbol].add(mk)
        return True
    return False

def main():
    strat = load_strategy(STRATEGY, STRATEGY_PARAMS)
    # 啟動前暖機最近 200 根 1H Bars
    warmup_1h = {s: [] for s in SYMBOLS}
    for s in SYMBOLS:
        _dfh = load_hourly_from_ticks(s, hours=200)
        warmup_1h[s] = [Bar(s, r.ts, r.o, r.h, r.l, r.c, int(getattr(r,'v',0))) for r in _dfh.itertuples()]
    strat.on_start(SYMBOLS, warmup_1h)
    broker = ShioajiBroker()
    broker.login()

    hour_builder = BarBuilder(frame="1H")
    last_key = {}
    stream = RedisTickStream()
    print("[LIVE] 啟動：PSAR 小時K決策 + tick 即時反轉 (MC next-bar 成交)")

    # MultiCharts 同步：bar 訊號於下一小時第一分鐘 open 成交
    MC_NEXT_BAR_FILL = True
    pending_orders = {s: None for s in SYMBOLS}
    seen_minute_first_tick = {s: set() for s in SYMBOLS}  # 記錄(YYYY-mm-dd HH:MM)是否已見第一筆

    while not STOP:
        try:
            now_local = datetime.now(tz)
            if not in_session(now_local):
                time.sleep(1); continue

            try:
                t = next(iter(stream))
            except StopIteration:
                time.sleep(0.1); continue

            # 先處理 MC 的下一小時第一分鐘 open 成交
            if MC_NEXT_BAR_FILL:
                po = pending_orders.get(t.symbol)
                if po is not None:
                    act_key = po.get('activate_key')
                    # 條件：這筆 tick 是該小時第一分鐘（:00）的第一筆
                    if _hour_key(t.ts) == act_key and t.ts.minute == 0 and _is_first_minute_open_tick(t.symbol, t.ts, seen_minute_first_tick):
                        side, qty = po['side'], int(po['qty'] or 1)
                        from strategy.core.events import Signal
                        broker.submit(Signal(t.symbol, side, qty, note='MC next-bar OPEN fill'))
                        pending_orders[t.symbol] = None

            # tick 級先跑風控/反轉
            sig_tick = strat.on_tick(t)
            if sig_tick:
                broker.submit(sig_tick)

            # 聚合出 1H bar，封口時產生 on_bar 訊號
            hour_builder.on_tick(t)
            key = t.ts.replace(minute=0, second=0, microsecond=0)
            last = last_key.get(t.symbol)
            if last is not None and key > last:
                for b in hour_builder.pop_closed_bars(t.symbol, key):
                    sig_bar = strat.on_bar(b)
                    if sig_bar:
                        broker.submit(sig_bar)
            last_key[t.symbol] = key

        except Exception as e:
            print(f"[LIVE][ERROR] {e}")
            time.sleep(1)
    strat.on_stop()
    broker.logout()
    print("[LIVE] 已關閉。")

if __name__ == "__main__":
    main()
