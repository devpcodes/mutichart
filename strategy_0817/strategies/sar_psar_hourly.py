# -*- coding: utf-8 -*-
from typing import Dict, List, Optional
from strategy.strategies.base import Strategy
from strategy.core.events import Bar, Tick, Signal

class PSARState:
    __slots__ = ("trend","sar","ep","af","prev_bar")  # trend: 1=long, -1=short

class PSARHourly(Strategy):
    def __init__(self, qty: int = 1, af: float = 0.02, af_max: float = 0.2, **_):
        self.qty = int(qty)
        self.af0 = float(af)
        self.afmax = float(af_max)
        self.state: Dict[str, PSARState] = {}
        self.cur_sar: Dict[str, float] = {}

    def _init_symbol(self, symbol: str, first_bar: Bar):
        st = PSARState()
        st.trend = 1 if first_bar.c >= first_bar.o else -1
        st.ep = first_bar.h if st.trend > 0 else first_bar.l
        st.sar = first_bar.l if st.trend > 0 else first_bar.h
        st.af = self.af0
        st.prev_bar = first_bar
        self.state[symbol] = st
        self.cur_sar[symbol] = st.sar

    def _update_psar(self, st: PSARState, prev_bar: Bar, bar: Bar):
        sar_next = st.sar + st.af * (st.ep - st.sar)
        if st.trend > 0:
            sar_next = min(sar_next, prev_bar.l, bar.l)
            if bar.h > st.ep:
                st.ep = bar.h
                st.af = min(self.afmax, st.af + self.af0)
            flipped = bar.l <= sar_next
            if flipped:
                st.trend = -1
                st.sar = st.ep
                st.ep = bar.l
                st.af = self.af0
            else:
                st.sar = sar_next
        else:
            sar_next = max(sar_next, prev_bar.h, bar.h)
            if bar.l < st.ep:
                st.ep = bar.l
                st.af = min(self.afmax, st.af + self.af0)
            flipped = bar.h >= sar_next
            if flipped:
                st.trend = 1
                st.sar = st.ep
                st.ep = bar.h
                st.af = self.af0
            else:
                st.sar = sar_next
        self.cur_sar[bar.symbol] = st.sar
        st.prev_bar = bar
        return flipped

    def on_start(self, symbols: List[str], warmup_bars: Dict[str, List[Bar]]) -> None:
        for s in symbols:
            bars = warmup_bars.get(s) or []
            if bars:
                self._init_symbol(s, bars[-1])

    def on_bar(self, bar: Bar) -> Optional[Signal]:
        st = self.state.get(bar.symbol)
        if not st:
            self._init_symbol(bar.symbol, bar)
            return None
        flipped = self._update_psar(st, st.prev_bar, bar)
        if flipped:
            side = "BUY" if st.trend > 0 else "SELL"
            return Signal(bar.symbol, side, self.qty, "PSAR flip (bar)")
        return None

    def on_tick(self, tick: Tick) -> Optional[Signal]:
        sar = self.cur_sar.get(tick.symbol)
        st = self.state.get(tick.symbol)
        if sar is None or st is None:
            return None
        if st.trend > 0 and tick.price <= sar:
            st.trend = -1; st.af = self.af0; st.ep = tick.price; st.sar = sar
            self.cur_sar[tick.symbol] = sar
            return Signal(tick.symbol, "SELL", self.qty, "PSAR flip (tick)")
        if st.trend < 0 and tick.price >= sar:
            st.trend = 1; st.af = self.af0; st.ep = tick.price; st.sar = sar
            self.cur_sar[tick.symbol] = sar
            return Signal(tick.symbol, "BUY", self.qty, "PSAR flip (tick)")
        return None

    def on_stop(self) -> None:
        pass

StrategyClass = PSARHourly
