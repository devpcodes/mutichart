# -*- coding: utf-8 -*-
import signal, time
from datetime import datetime, time as dtime
import pytz

from strategy.config import SYMBOLS, STRATEGY, STRATEGY_PARAMS, SESSION, TIMEZONE
from strategy.core.registry import load_strategy
from strategy.core.barbuilder import BarBuilder
from strategy.core.datafeed import RedisTickStream
from strategy.core.calendar import is_third_wed_1329
from strategy.storage.mysql import load_hourly_from_ticks
from strategy.core.events import Bar
from strategy.broker.shioaji_broker import ShioajiBroker
from strategy.logging_setup import setup_logging
from dotenv import load_dotenv
setup_logging(app_name="live")
load_dotenv()
STOP = False
def _handle_sig(signum, frame):
    global STOP
    print("\n[SYS] 收到終止訊號，準備優雅關閉...")
    STOP = True

signal.signal(signal.SIGINT, _handle_sig)
signal.signal(signal.SIGTERM, _handle_sig)
tz = pytz.timezone(TIMEZONE)


def _net_position(broker, symbol: str) -> int:
    try:
        pos_list = broker.list_positions()
    except Exception as e:
        print(f"[POS][ERR] list_positions failed: {e}")
        return 0
    net = 0
    def _to_dict(x):
        if isinstance(x, dict): return x
        d = {}
        for k in dir(x):
            if k.startswith('_'): continue
            try: v = getattr(x, k)
            except: continue
            if callable(v): continue
            d[k] = v
        return d
    for p in pos_list or []:
        d = _to_dict(p)
        code = str(d.get('code') or d.get('symbol') or d.get('contract', ''))
        if hasattr(d.get('contract', None), 'code'):
            try: code = d['contract'].code or code
            except: pass
        if not code: continue
        if not (code == symbol or code.startswith(symbol)): continue
        qty  = int(d.get('qty') or d.get('quantity') or d.get('position') or 0)
        side = str(d.get('direction') or d.get('bs') or d.get('side') or d.get('action') or '').upper()
        if   side in ('LONG','B','BUY'):   net += qty
        elif side in ('SHORT','S','SELL'): net -= qty
        else:
            try: net += int(d.get('net_qty', 0))
            except: pass
    return net

def submit_signal(broker, sig) -> None:
    try:
        side   = (getattr(sig, "side", "") or "").upper()
        symbol = getattr(sig, "symbol", None)
        qty    = int(getattr(sig, "qty", 1) or 1)
        # .env override for qty if present
        try:
            import os
            qty = int(os.getenv("ORDER_QTY", qty))
        except Exception:
            pass
        if not symbol or side not in ("BUY","SELL","FLAT"):
            print(f"[SIGNAL][SKIP] invalid signal: {sig}")
            return
        if side == "FLAT":
            net = _net_position(broker, symbol)
            if net == 0:
                print(f"[FLAT] {symbol}: 無淨部位，不需平倉")
                return
            action = "Sell" if net > 0 else "Buy"
            mt = _market_type_now()
            resp = broker.place_order_futures(symbol=symbol, code=None, action=action, qty=abs(net),
                                              price=None, price_type="MKT", order_type="IOC",
                                              oc_type="Close", market_type=mt)
            if getattr(resp, "ok", False):
                print(f"[FLAT][OK] {symbol} {action} x{abs(net)} (IOC Close, {mt})")
            else:
                print(f"[FLAT][ERR] {symbol} {action} x{abs(net)} | {getattr(resp,'err',None)}")
            return
        action = "Buy" if side == "BUY" else "Sell"
        mt = _market_type_now()
        resp = broker.place_order_futures(symbol=symbol, code=None, action=action, qty=qty,
                                          price=None, price_type="MKT", order_type="IOC",
                                          oc_type="Auto", market_type=mt)
        if getattr(resp, "ok", False):
            print(f"[ORDER][OK] {symbol} {action} x{qty} (IOC, {mt})")
        else:
            print(f"[ORDER][ERR] {symbol} {action} x{qty} | {getattr(resp,'err',None)}")
    except Exception as e:
        print(f"[ORDER][EXC] {e}")

from datetime import time as dtime

def _market_type_now() -> str:
    now_t = datetime.now(tz).time()
    return "Night" if (now_t >= dtime(15, 0) or now_t < dtime(5, 0)) else "Day"

def in_session(now_local: datetime) -> bool:
    """是否在交易時段；支援跨午夜（例 15:00–05:00）。"""
    t = now_local.time()
    for s, e in SESSION:
        if s <= e:
            if s <= t <= e: return True
        else:
            if t >= s or t <= e: return True
    return False

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
                        submit_signal(broker, Signal(t.symbol, side, qty, note='MC next-bar OPEN fill'))
                        pending_orders[t.symbol] = None

            # tick 級先跑風控/反轉
            sig_tick = strat.on_tick(t)
            if sig_tick:
                submit_signal(broker, sig_tick)

            # 聚合出 1H bar，封口時產生 on_bar 訊號
            hour_builder.on_tick(t)
            key = t.ts.replace(minute=0, second=0, microsecond=0)
            last = last_key.get(t.symbol)
            if last is not None and key > last:
                for b in hour_builder.pop_closed_bars(t.symbol, key):
                    sig_bar = strat.on_bar(b)
                    if sig_bar:
                        submit_signal(broker, sig_bar)
            last_key[t.symbol] = key

        except Exception as e:
            print(f"[LIVE][ERROR] {e}")
            time.sleep(1)

    strat.on_stop()
    try:
        broker.logout()
    except Exception as e:
        print(f"[LOGOUT][WARN] {e}")
    print("[LIVE] 已關閉。")

if __name__ == "__main__":
    main()
