# -*- coding: utf-8 -*-
from collections import defaultdict
from datetime import datetime
from typing import Dict, List
from strategy.core.events import Tick, Bar

def _floor_key(ts: datetime, frame: str) -> datetime:
    f = frame.lower()
    if f in ("1h", "60min", "hour", "1hour"):
        return ts.replace(minute=0, second=0, microsecond=0)
    return ts.replace(second=0, microsecond=0)  # 1min

class BarBuilder:
    def __init__(self, frame: str = "1min"):
        self.frame = frame
        self.state: Dict[str, Dict[datetime, Dict[str, float]]] = defaultdict(dict)

    def on_tick(self, t: Tick):
        key = _floor_key(t.ts, self.frame)
        bucket = self.state[t.symbol].get(key)
        if not bucket:
            self.state[t.symbol][key] = bucket = {"o": t.price, "h": t.price, "l": t.price, "c": t.price, "v": t.vol}
        else:
            bucket["h"] = max(bucket["h"], t.price)
            bucket["l"] = min(bucket["l"], t.price)
            bucket["c"] = t.price
            bucket["v"] += t.vol

    def pop_closed_bars(self, symbol: str, now_key: datetime) -> List[Bar]:
        out: List[Bar] = []
        buckets = self.state[symbol]
        for k in sorted(list(buckets.keys())):
            if k < now_key:
                s = buckets.pop(k)
                out.append(Bar(symbol, k, s["o"], s["h"], s["l"], s["c"], int(s["v"])))
        return out
