# -*- coding: utf-8 -*-
from pathlib import Path
import argparse
import pandas as pd

from strategy.config import SYMBOLS, STRATEGY, STRATEGY_PARAMS, FEED_FRAME, BAR_FRAME
from strategy.core.registry import load_strategy
from strategy.core.events import Tick
from strategy.core.barbuilder import BarBuilder
from strategy.core.backtester import BacktestEngine
from strategy.storage.mysql import load_history, load_hourly_from_ticks

# ---- 本檔內部補一個最基本的 Bar 類別（避免 NameError；簽名需與現有呼叫一致）----
class Bar:
    def __init__(self, symbol, ts, o, h, l, c, v=0):
        self.symbol = symbol  # 商品代號：MXF / TXF
        self.ts = ts          # pandas.Timestamp
        self.o = float(o)     # 開
        self.h = float(h)     # 高
        self.l = float(l)     # 低
        self.c = float(c)     # 收
        self.v = int(v)       # 量

    def __repr__(self):
        return f"Bar({self.symbol}, {self.ts}, O:{self.o}, H:{self.h}, L:{self.l}, C:{self.c}, V:{self.v})"
# -------------------------------------------------------------------------

OUT_DIR = Path("backtest_out")

# MultiCharts 同步：bar 訊號於下一小時「第一分鐘的 open tick」成交
MC_NEXT_BAR_FILL = True

def is_first_minute_open_tick(tick: Tick) -> bool:
    """此回測中，我們以「雙 tick（open→close）」近似 intrabar；
    其中 open tick 由 Tick.is_open=True 標示（在 events.Tick 已新增 is_open）。"""
    return getattr(tick, "is_open", False) and tick.ts.minute == 0

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="MXF", help="個別商品（TXF 或 MXF），預設 MXF")
    parser.add_argument("--limit", type=int, default=120000, help="每商品讀取 1min 筆數上限")
    args = parser.parse_args()
    single_symbol = args.symbol.upper()

    # 讀 1 分鐘 K（近似 tick；可在 storage 設 only_day=True 過濾日盤）
    data_1m = {s: load_history(s, limit_bars=args.limit, frame=FEED_FRAME) for s in SYMBOLS}

    # 策略 + 回測引擎
    strat = load_strategy(STRATEGY, STRATEGY_PARAMS)
    engine = BacktestEngine(start_cash=1_000_000)

    # 小時K聚合器
    hour_builder = BarBuilder(frame=BAR_FRAME)
    last_key = {}

    # ---- 暖機：最近 200 根 1H Bars，餵給策略初始化（PSAR 需要歷史序列）----
    warmup_1h = {s: [] for s in SYMBOLS}
    for s in SYMBOLS:
        _dfh = load_hourly_from_ticks(s, hours=200)
        warmup_1h[s] = [Bar(s, r.ts, r.o, r.h, r.l, r.c, int(getattr(r, 'v', 0))) for r in _dfh.itertuples()]
    strat.on_start(SYMBOLS, warmup_1h)
    # -----------------------------------------------------------------------

    # 準備 tick 串列（雙 tick：先 minute open，再 minute close），較貼近 MC 的 intrabar 行為
    ticks = []
    for s, df in data_1m.items():
        for r in df.itertuples():
            # 先 minute open
            ticks.append(Tick(s, r.ts, float(r.o), int(getattr(r, 'v', 0)), is_open=True))
            # 再 minute close
            ticks.append(Tick(s, r.ts, float(r.c), int(getattr(r, 'v', 0)), is_open=False))
    # 保證 open tick 先於 close tick
    ticks.sort(key=lambda t: (t.ts, t.symbol, 0 if getattr(t, "is_open", False) else 1))

    # MC 模式：儲存「待成交的 bar 訊號」
    # pending_orders[symbol] = {"side": "BUY"/"SELL", "qty": int, "activate_key": hour_key}
    pending_orders = {s: None for s in SYMBOLS}

    # 逐「近似 tick」回放
    for t in ticks:
        # --- 先處理 MC 的「下一小時第一分鐘 open」成交 ---
        if MC_NEXT_BAR_FILL:
            key_first_min_of_hour = t.ts.replace(minute=0, second=0, microsecond=0)
            po = pending_orders.get(t.symbol)
            if po is not None and po.get("activate_key") == key_first_min_of_hour and is_first_minute_open_tick(t):
                side = po["side"]
                qty = int(po["qty"] or 1)
                from strategy.core.events import Signal
                sig = Signal(t.symbol, side, qty, note="MC next-bar OPEN fill")
                engine.on_tick(t, sig)   # 以此 open tick 價成交
                pending_orders[t.symbol] = None  # 清空待成交

        # --- tick 級：即時判斷（PSAR flip/tick 等） ---
        sig_tick = strat.on_tick(t)
        engine.on_tick(t, sig_tick)

        # --- 小時聚合：封口才做 on_bar（PSAR flip/bar） ---
        hour_builder.on_tick(t)
        key = t.ts.replace(minute=0, second=0, microsecond=0)
        last = last_key.get(t.symbol)

        if last is not None and key > last:
            # 代表上一小時剛封口：取出上一小時的 bar
            closed = hour_builder.pop_closed_bars(t.symbol, key)
            for b in closed:
                sig_bar = strat.on_bar(b)
                if MC_NEXT_BAR_FILL and sig_bar:
                    # 安排到「下一小時第一分鐘 open」成交（activate_key = 新小時 key）
                    pending_orders[t.symbol] = {
                        "side": sig_bar.side,
                        "qty": int(sig_bar.qty or 1),
                        "activate_key": key
                    }
                else:
                    # 非 MC 模式：直接用 bar 收盤成交
                    engine.on_bar_signal(b, sig_bar)

        last_key[t.symbol] = key

    # 收尾：把未平倉部位結算
    if ticks:
        engine.close_all(ticks[-1].ts)

    # 結果與輸出
    res = engine.results()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    res["trades_df"].to_csv(OUT_DIR / "trades.csv", index=False, encoding="utf-8-sig")
    res["equity_df"].to_csv(OUT_DIR / "equity.csv", index=False, encoding="utf-8-sig")

    print("=== 回測摘要（整體） ===")
    print(f"初始資金        : {res['start_cash']:.2f}")
    print(f"最終資產        : {res['end_equity']:.2f}")
    print(f"總報酬率        : {res['total_return']*100:.2f}%")
    print(f"夏普比率(日)    : {res['sharpe_daily']:.3f}")
    print(f"最大回撤        : {res['max_drawdown']*100:.2f}%")
    print(f"交易次數        : {res['num_trades']}")
    print(f"勝率            : {res['win_rate']*100:.2f}%")
    print(f"平均單筆損益    : {res['avg_trade_pnl']:.2f}")
    print(f"總交易損益      : {res['total_trade_pnl']:.2f}")
    print(f"檔案已儲存      : {OUT_DIR/'trades.csv'}, {OUT_DIR/'equity.csv'}")

    # 個別商品平倉權益曲線（預設 MXF，可用 --symbol 切換 TXF）
    trades_df_all = res["trades_df"].copy()
    if trades_df_all.empty:
        print("沒有任何交易紀錄，無法產出個別商品結果。")
        return

    sub = trades_df_all[trades_df_all["symbol"].astype(str).str.startswith(single_symbol)].dropna(subset=["exit_ts"]).copy()
    if sub.empty:
        print(f"沒有 {single_symbol} 的已平倉交易，無法產出個別商品結果。")
        return

    sub["exit_ts"] = pd.to_datetime(sub["exit_ts"])
    sub.sort_values("exit_ts", inplace=True)
    sub["cum_realized"] = sub["pnl"].cumsum()
    single_eq = sub.loc[:, ["exit_ts", "cum_realized"]].rename(columns={"exit_ts": "ts", "cum_realized": "realized_pnl"})
    single_eq["equity_from_start"] = res["start_cash"] + single_eq["realized_pnl"]

    out_trades_csv = OUT_DIR / f"trades_{single_symbol.lower()}.csv"
    out_eq_csv     = OUT_DIR / f"equity_{single_symbol.lower()}.csv"
    sub.to_csv(out_trades_csv, index=False, encoding="utf-8-sig")
    single_eq.to_csv(out_eq_csv, index=False, encoding="utf-8-sig")

    try:
        import matplotlib.pyplot as plt
        plt.figure(figsize=(10, 4))
        plt.plot(single_eq["ts"], single_eq["realized_pnl"])
        plt.title(f"{single_symbol} 平倉權益曲線（PSAR 策略 / MC 同步）")
        plt.xlabel("時間"); plt.ylabel("累積損益")
        plt.tight_layout()
        out_png = OUT_DIR / f"equity_{single_symbol.lower()}.png"
        plt.savefig(out_png, dpi=150)
        print(f"已輸出 {single_symbol} 個別結果：{out_trades_csv}、{out_eq_csv}、{out_png}")
    except Exception:
        print(f"已輸出 {single_symbol} 個別結果：{out_trades_csv}、{out_eq_csv}（如需 PNG，請安裝 matplotlib）")

if __name__ == "__main__":
    main()
