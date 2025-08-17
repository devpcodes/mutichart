# -*- coding: utf-8 -*-
from dataclasses import dataclass
from typing import Optional
import pandas as pd

@dataclass
class Tick:
    symbol: str
    ts: pd.Timestamp
    price: float
    vol: int = 0
    is_open: bool = False

@dataclass
class Bar:
    symbol: str
    ts: pd.Timestamp  # bar 開始時間
    o: float
    h: float
    l: float
    c: float
    v: int

@dataclass
class Signal:
    symbol: str
    side: str    # 'BUY' / 'SELL' / 'FLAT'
    qty: int = 1
    note: Optional[str] = None
