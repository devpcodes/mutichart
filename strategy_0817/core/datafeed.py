# -*- coding: utf-8 -*-
import json
import redis
import pandas as pd
from strategy.config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_CHANNEL_PREFIX
from strategy.core.events import Tick

class RedisTickStream:
    def __init__(self):
        self.r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
        self.pubsub = self.r.pubsub()
        self.pubsub.psubscribe(f"{REDIS_CHANNEL_PREFIX}*")

    def __iter__(self): return self

    def __next__(self) -> Tick:
        msg = self.pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        if not msg:
            raise StopIteration
        data = json.loads(msg["data"])
        ts = pd.to_datetime(data.get("timestamp"))
        return Tick(symbol=data["symbol"], ts=ts, price=float(data["price"]), vol=int(data.get("vol",0)))
