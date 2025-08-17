
# -*- coding: utf-8 -*-
import logging
from dataclasses import dataclass
from typing import Dict, Optional
from datetime import datetime

from strategy.broker.shioaji_broker import ShioajiBroker

log = logging.getLogger("TradeExecutor")
EXEC_LOGGER = logging.getLogger("ExecFlow")

@dataclass
class RiskConfig:
    max_pos_per_symbol: int = 2
    daily_loss_limit: float = 20000.0
    throttle_sec: float = 1.0
    market_type: str = "Day"

@dataclass
class PosState:
    position: int = 0
    last_ts: Optional[datetime] = None
    day_pnl: float = 0.0

class TradeExecutor:
    def __init__(self, broker: ShioajiBroker, risk: RiskConfig | None = None):
        self.broker = broker
        self.risk = risk or RiskConfig()
        self.state: Dict[str, PosState] = {}

    def _st(self, symbol: str) -> PosState:
        if symbol not in self.state:
            self.state[symbol] = PosState()
        return self.state[symbol]

    def flatten_symbol(self, symbol: str, code: Optional[str] = None):
        st = self._st(symbol)
        if st.position == 0:
            return
        action = "Sell" if st.position > 0 else "Buy"
        qty = abs(st.position)
        resp = self.broker.place_order_futures(
            symbol, code, action=action, qty=qty,
            price=None, price_type="MKT", order_type="IOC",
            oc_type="Auto", market_type=self.risk.market_type
        )
        if resp.ok:
            EXEC_LOGGER.info("FLATTEN OK %s", {"symbol": symbol, "qty": qty})
            log.info("[FLATTEN] %s %s x%d OK", symbol, action, qty)
            st.position = 0
        else:
            EXEC_LOGGER.error("FLATTEN ERR %s", {"symbol": symbol, "qty": qty, "error": resp.err})
            log.error("[FLATTEN-ERR] %s", resp.err)

    def handle_signal(self, symbol: str, side: str, qty: int = 1, code: Optional[str] = None):
        st = self._st(symbol)
        action = "Buy" if side.upper() == "BUY" else "Sell"
        resp = self.broker.place_order_futures(
            symbol, code, action=action, qty=int(qty),
            price=None, price_type="MKT", order_type="IOC",
            oc_type="Auto", market_type=self.risk.market_type
        )
        if resp.ok:
            st.position += 1 if action == "Buy" else -1
            EXEC_LOGGER.info("SIG-ORDER OK %s", {"symbol": symbol, "side": side, "qty": int(qty), "new_pos": st.position})
            log.info("[ORDER] %s %s x%d OK | pos=%d", symbol, action, qty, st.position)
        else:
            EXEC_LOGGER.error("SIG-ORDER ERR %s", {"symbol": symbol, "side": side, "qty": int(qty), "error": resp.err})
            log.error("[ORDER-ERR] %s", resp.err)

    def flatten_all(self):
        for sym in list(self.state.keys()):
            self.flatten_symbol(sym)
