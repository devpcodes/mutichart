# -*- coding: utf-8 -*-
from dataclasses import dataclass
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
from strategy.core.events import Bar, Tick, Signal
from strategy.config import MULTIPLIER, TIMEZONE
from strategy.core.calendar import is_third_wed_1329
import pytz

SLIPPAGE = 0.0
FEE_PER_CONTRACT = 0.0

@dataclass
class Position:
    side: int = 0
    qty: int = 0
    avg_price: float = 0.0

@dataclass
class Trade:
    symbol: str
    side: str
    qty: int
    entry_ts: pd.Timestamp
    entry_price: float
    exit_ts: pd.Timestamp
    exit_price: float
    pnl: float
    bars_held: int

class BacktestEngine:
    def __init__(self, start_cash: float = 1_000_000.0):
        self.start_cash = float(start_cash)
        self.equity = self.start_cash
        self.positions: Dict[str, Position] = {}
        self.last_close: Dict[str, float] = {}
        self.trades: List[Trade] = []
        self.equity_records: List[Dict] = []
        self.open_trade_idx: Dict[str, int] = {}
        self.tz = pytz.timezone(TIMEZONE)

    def _mult(self, symbol: str) -> float:
        for k, v in MULTIPLIER.items():
            if symbol.startswith(k):
                return float(v)
        return 1.0

    def _close_trade(self, sym: str, ts: pd.Timestamp, price: float):
        if sym not in self.open_trade_idx:
            return
        idx = self.open_trade_idx.pop(sym)
        tr = self.trades[idx]
        mult = self._mult(sym)
        sign = 1 if tr.side == "LONG" else -1
        pnl = (price - tr.entry_price) * sign * tr.qty * mult
        pnl -= FEE_PER_CONTRACT * tr.qty
        tr.exit_ts = ts
        tr.exit_price = price
        tr.pnl = pnl
        self.equity += pnl
        self.positions[sym] = Position()

    def on_tick(self, tick: Tick, signal_from_strategy: Optional[Signal] = None):
        sym = tick.symbol
        mult = self._mult(sym)
        prev_close = self.last_close.get(sym)
        if prev_close is not None:
            pos = self.positions.get(sym, Position())
            dprice = (tick.price - prev_close)
            self.equity += pos.side * pos.qty * dprice * mult
        self.last_close[sym] = tick.price

        # 自動平倉（每月第三個週三 13:29）
        if is_third_wed_1329(tick.ts.to_pydatetime() if hasattr(tick.ts, 'to_pydatetime') else tick.ts):
            pos = self.positions.get(sym, Position())
            if pos.side != 0:
                self._close_trade(sym, tick.ts, tick.price)

        sig = signal_from_strategy
        if sig:
            target_side = 1 if sig.side.upper() == "BUY" else -1 if sig.side.upper() == "SELL" else 0
            qty = int(sig.qty or 1)
            fill_price = tick.price + (SLIPPAGE * (1 if target_side>0 else -1 if target_side<0 else 0))
            cur = self.positions.get(sym, Position())
            if cur.side != 0 and target_side != 0 and cur.side != target_side:
                self._close_trade(sym, tick.ts, fill_price)
            if target_side == 0:
                if cur.side != 0:
                    self._close_trade(sym, tick.ts, fill_price)
                return
            if sym in self.open_trade_idx:
                self._close_trade(sym, tick.ts, fill_price)
            side_str = "LONG" if target_side == 1 else "SHORT"
            self.trades.append(Trade(sym, side_str, qty, tick.ts, fill_price, pd.NaT, np.nan, 0.0, 0))
            self.open_trade_idx[sym] = len(self.trades)-1
            self.positions[sym] = Position(side=target_side, qty=qty, avg_price=fill_price)

        self.equity_records.append({"ts": tick.ts, "equity": self.equity})

    def on_bar_signal(self, bar: Bar, signal_from_strategy: Optional[Signal] = None):
        if not signal_from_strategy:
            return
        tick_like = Tick(bar.symbol, bar.ts, bar.c, bar.v)
        self.on_tick(tick_like, signal_from_strategy)

    def close_all(self, ts: pd.Timestamp):
        for sym in list(self.open_trade_idx.keys()):
            last_price = self.last_close.get(sym)
            if last_price is None: continue
            self._close_trade(sym, ts, last_price)

    def results(self) -> Dict:
        eq = pd.DataFrame(self.equity_records).drop_duplicates("ts").set_index("ts").sort_index()
        eq["ret"] = eq["equity"].pct_change().fillna(0.0)
        daily = eq["equity"].resample("1D").last().dropna()
        daily_ret = daily.pct_change().dropna()
        sharpe = (daily_ret.mean() / (daily_ret.std() + 1e-12)) * np.sqrt(252) if len(daily_ret) else 0.0
        roll_max = eq["equity"].cummax() if len(eq) else pd.Series(dtype=float)
        dd = eq["equity"] / roll_max - 1.0 if len(eq) else pd.Series(dtype=float)
        max_dd = dd.min() if len(dd) else 0.0
        trades_df = pd.DataFrame([t.__dict__ for t in self.trades])
        win_rate = float((trades_df["pnl"] > 0).mean()) if len(trades_df) else 0.0
        avg_pnl = float(trades_df["pnl"].mean()) if len(trades_df) else 0.0
        total_pnl = float(trades_df["pnl"].sum()) if len(trades_df) else 0.0
        return {
            "start_cash": self.start_cash,
            "end_equity": float(eq["equity"].iloc[-1]) if len(eq) else self.start_cash,
            "total_return": float(eq["equity"].iloc[-1] / self.start_cash - 1.0) if len(eq) else 0.0,
            "sharpe_daily": float(sharpe),
            "max_drawdown": float(max_dd),
            "num_trades": int(len(trades_df)),
            "win_rate": float(win_rate),
            "avg_trade_pnl": float(avg_pnl),
            "total_trade_pnl": float(total_pnl),
            "equity_df": eq.reset_index(),
            "trades_df": trades_df,
        }
