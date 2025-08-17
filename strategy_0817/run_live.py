# -*- coding: utf-8 -*-
import signal
import time
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

SYMBOLS = ["MXF"]

# --- logging & env ---
setup_logging(app_name="live")
load_dotenv()  # 讓 ShioajiBroker 能從 .env 讀 API_KEY/SECRET_KEY/SIMULATION/...

STOP = False
def _handle_sig(signum, frame):
    global STOP
    print("\n[SYS] 收到終止訊號，準備優雅關閉...")
    STOP = True

signal.signal(signal.SIGINT, _handle_sig)
signal.signal(signal.SIGTERM, _handle_sig)

tz = pytz.timezone(TIMEZONE)

def in_session(now_local: datetime) -> bool:
    """判斷是否在交易時段（由 config.SESSION 控制）。"""
    t = now_local.time()
    return any(s <= t <= e for s, e in SESSION)

# --- 訊號 → 下單（IOC 市價） ---
def submit_signal(broker: ShioajiBroker, sig) -> None:
    """
    把策略的 Signal 轉成券商委託；全用 IOC 市價單。
    支援 side: BUY / SELL；FLAT 暫先僅記錄（如需自動平倉可再加）。
    """
    try:
        side = (getattr(sig, "side", "") or "").upper()
        symbol = getattr(sig, "symbol", None)
        qty = int(getattr(sig, "qty", 1) or 1)
        note = getattr(sig, "note", None)

        if not symbol or side not in ("BUY", "SELL", "FLAT"):
            print(f"[SIGNAL][SKIP] invalid signal: {sig}")
            return

        if side == "FLAT":
            # TODO: 若要自動平倉：查詢持倉 → 送反向單；目前先記錄即可
            print(f"[SIGNAL][FLAT] 平倉尚未實作（僅記錄）：{sig}")
            return

        action = "Buy" if side == "BUY" else "Sell"

        resp = broker.place_order_futures(
            symbol=symbol, code=None,
            action=action, qty=qty,
            price=None,            # 市價
            price_type="MKT",      # 市價
            order_type="IOC",      # ✅ IOC
            oc_type="Auto",
            market_type="Day"      # 如需夜盤下單可改 "Night" 或做成設定
        )
        if getattr(resp, "ok", False):
            print(f"[ORDER][OK] {symbol} {action} x{qty} (IOC) | note={note}")
        else:
            print(f"[ORDER][ERR] {symbol} {action} x{qty} (IOC) | {getattr(resp,'err',None)}")
    except Exception as e:
        print(f"[ORDER][EXC] {e}")

# --- 工具 ---
def _hour_key(ts: datetime) -> str:
    """回傳小時聚合的 key（yyyy-mm-dd HH:00）"""
    return ts.strftime("%Y-%m-%d %H:00")

def _minute_key(ts: datetime) -> str:
    """回傳分鐘聚合的 key（yyyy-mm-dd HH:MM）"""
    return ts.strftime("%Y-%m-%d %H:%M")

def _is_first_minute_of_hour(ts: datetime) -> bool:
    return ts.minute == 0

def _first_minute_open_tick(symbol: str, ts: datetime, seen_first_tick_dict: dict) -> bool:
    """
    是否為該商品在該分鐘看到的第一筆 tick（用於 MC 下一棒 open 成交）。
    """
    key = _minute_key(ts)
    seen = seen_first_tick_dict.setdefault(symbol, set())
    if key in seen:
        return False
    seen.add(key)
    return True

# --- 主程式 ---
def main():
    global STOP

    strat = load_strategy(STRATEGY, STRATEGY_PARAMS or {})
    print(f"[LIVE] 載入策略：{STRATEGY} 參數：{STRATEGY_PARAMS}")

    # 暖機最近 200 根 1H Bars（由 DB ticks 聚成 1H）
    warmup_1h = {s: [] for s in SYMBOLS}
    for s in SYMBOLS:
        _dfh = load_hourly_from_ticks(s, hours=200, only_day=False)  # 日夜盤都吃
        warmup_1h[s] = [Bar(s, r.ts, r.o, r.h, r.l, r.c, int(getattr(r, 'v', 0))) for r in _dfh.itertuples()]
    strat.on_start(SYMBOLS, warmup_1h)

    # 券商登入
    broker = ShioajiBroker()
    broker.login()

    # 即時資料與 Bar 聚合
    hour_builder = BarBuilder(frame="1H")
    last_key = {}
    stream = RedisTickStream()
    print("[LIVE] 啟動：PSAR 小時K決策 + tick 即時反轉 (MC next-bar 成交)")

    # MultiCharts 同步：bar 訊號於下一小時第一分鐘 open 成交
    MC_NEXT_BAR_FILL = True
    pending_orders = {s: None for s in SYMBOLS}
    seen_minute_first_tick = {s: set() for s in SYMBOLS}  # 記錄(YYYY-mm-dd HH:MM)是否已見第一筆

    # 交易時間控制
    while not STOP:
        try:
            msg = stream.__next__()  # 可能拋 StopIteration
            t = msg  # Tick(symbol, ts, price, vol, ...)

            # 非交易時段不處理（保留 if 需要日夜盤以外控制）
            now_local = t.ts.tz_localize(None).tz_localize(tz) if t.ts.tzinfo is None else t.ts.astimezone(tz)
            if not in_session(now_local) and not is_third_wed_1329(now_local):
                # 仍讓 hour_builder 聚合資料，以免跨時段接續出錯；但不出訊號
                hour_builder.on_tick(t)
                # 這裡可視需求加入 sleep(0) 或略過
                continue

            # --- MC 下一棒開盤成交（延遲成交的 pending orders）---
            if MC_NEXT_BAR_FILL:
                # 若此刻是整點的第一分鐘之第一筆 tick，且有 pending_order → 送單
                act_key = _hour_key(t.ts)
                po = pending_orders.get(t.symbol)
                if po:
                    # 當前 tick 所屬小時鍵
                    if _is_first_minute_of_hour(t.ts) and _first_minute_open_tick(t.symbol, t.ts, seen_minute_first_tick):
                        side, qty = po['side'], int(po.get('qty') or 1)
                        from strategy.core.events import Signal
                        submit_signal(broker, Signal(t.symbol, side, qty, note='MC next-bar OPEN fill'))
                        pending_orders[t.symbol] = None

            # --- Tick 級先跑策略（若策略有 on_tick）---
            if hasattr(strat, "on_tick"):
                sig_tick = strat.on_tick(t)
                if sig_tick:
                    submit_signal(broker, sig_tick)

            # --- 聚合 1H bar，封口時觸發 on_bar ---
            hour_builder.on_tick(t)
            key = _hour_key(t.ts)
            if last_key.get(t.symbol) != key:
                # 小時切換邊界：處理封口的 bars
                for b in hour_builder.pop_closed_bars(t.symbol, key):
                    sig_bar = strat.on_bar(b)
                    if sig_bar:
                        if MC_NEXT_BAR_FILL:
                            # 先掛成 pending，下一小時第一分鐘第一筆 tick 才成交
                            pending_orders[t.symbol] = {"side": getattr(sig_bar, "side", "").upper(), "qty": int(getattr(sig_bar, "qty", 1) or 1)}
                        else:
                            submit_signal(broker, sig_bar)
                last_key[t.symbol] = key

        except StopIteration:
            # 沒訊息就稍等
            time.sleep(0.1)
        except Exception as e:
            print(f"[LIVE][ERROR] {e}")
            time.sleep(1)

    # 關閉
    strat.on_stop()
    broker.logout()
    print("[LIVE] 已關閉。")

if __name__ == "__main__":
    main()
