
# -*- coding: utf-8 -*-
import os
import logging
from dataclasses import dataclass
from typing import Callable, Optional, Dict

import shioaji as sj

log = logging.getLogger("ShioajiBroker")
ORDER_LOGGER = logging.getLogger("OrderExec")

@dataclass
class FutOrderResp:
    ok: bool
    order: dict | None = None
    err: str | None = None

class ShioajiBroker:
    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        simulation: Optional[bool] = None,
        ca_path: Optional[str] = None,
        ca_passwd: Optional[str] = None,
        person_id: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("API_KEY", "")
        self.secret_key = secret_key or os.getenv("SECRET_KEY", "")
        self.simulation = (
            (os.getenv("SIMULATION", "true").lower() == "true")
            if simulation is None else simulation
        )
        self.ca_path = ca_path or os.getenv("CA_PATH", "")
        self.ca_passwd = ca_passwd or os.getenv("CA_PASSWD", "")
        self.person_id = person_id or os.getenv("PERSON_ID", "")
        self.api: sj.Shioaji | None = None
        self._contracts_cache: Dict[str, sj.contracts.Contract] = {}
        self.quote_ready = False

    def login(self) -> dict:
        self.api = sj.Shioaji(simulation=self.simulation)
        log.info("Shioaji login(simulation=%s)...", self.simulation)
        accounts = self.api.login(api_key=self.api_key, secret_key=self.secret_key)
        if hasattr(self.api, "futopt_account"):
            self.api.set_default_account(self.api.futopt_account)
        if not self.simulation:
            ok = self.api.activate_ca(
                ca_path=self.ca_path,
                ca_passwd=self.ca_passwd,
                person_id=self.person_id,
            )
            if not ok:
                raise RuntimeError("activate_ca failed, check CA settings.")
        log.info("Shioaji login OK.")
        return accounts

    def logout(self):
        if self.api:
            self.api.logout()
            self.api = None
            self._contracts_cache.clear()
            self.quote_ready = False
            log.info("Shioaji logout.")

    def get_contract(self, symbol: str, code: Optional[str] = None):
        assert self.api is not None
        key = f"{symbol}:{code or 'nearest'}"
        if key in self._contracts_cache:
            return self._contracts_cache[key]
        cbook = getattr(self.api.Contracts.Futures, symbol)
        if code:
            c = cbook[code]
        else:
            keys = sorted([k for k in dir(cbook) if k.startswith(symbol)])
            if not keys:
                raise RuntimeError(f"No contract for {symbol}")
            c = cbook[keys[0]]
        self._contracts_cache[key] = c
        return c

    def place_order_futures(
        self,
        symbol: str,
        code: Optional[str],
        action: str,
        qty: int,
        price: float | None = None,
        price_type: str = "MKT",
        order_type: str = "IOC",
        oc_type: str = "Auto",
        market_type: str = "Day"
    ) -> FutOrderResp:
        assert self.api is not None
        c = self.get_contract(symbol, code)
        order = self.api.Order(
            price=price if price_type == "LMT" else 0,
            quantity=int(qty),
            action=action,
            price_type=price_type,
            order_type=order_type,
            octype=oc_type,
            market_type=market_type,
        )
        try:
            ORDER_LOGGER.info("PRE-ORDER %s", {
                "symbol": symbol,
                "code": (code or getattr(c, "code", "")),
                "action": action,
                "qty": int(qty),
                "price": price,
                "price_type": price_type,
                "order_type": order_type,
                "oc_type": oc_type,
                "market_type": market_type,
                "simulation": self.simulation,
            })
            trade = self.api.place_order(c, order)
            to_dict = getattr(trade, "_asdict", None)
            payload = to_dict() if to_dict else {"trade": str(trade)}
            ORDER_LOGGER.info("POST-ORDER %s", payload)
            return FutOrderResp(ok=True, order=payload)
        except Exception as e:
            ORDER_LOGGER.error("ORDER-ERROR %s", {
                "symbol": symbol,
                "code": (code or getattr(c, "code", "")),
                "action": action,
                "qty": int(qty),
                "price": price,
                "error": str(e),
            })
            return FutOrderResp(ok=False, err=str(e))

    def cancel_order(self, ordno: str):
        assert self.api is not None
        return self.api.cancel_order(ordno)

    def list_orders(self):
        assert self.api is not None
        return self.api.list_orders()

    def list_positions(self):
        assert self.api is not None
        if hasattr(self.api, "list_positions"):
            return self.api.list_positions()
        if hasattr(self.api, "list_trades"):
            return self.api.list_trades()
        return []
