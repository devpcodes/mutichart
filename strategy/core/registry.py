# -*- coding: utf-8 -*-
from importlib import import_module

def load_strategy(name: str, params: dict):
    mod = import_module(f"strategy.strategies.{name}")
    return mod.StrategyClass(**params)
