# -*- coding: utf-8 -*-
from datetime import datetime, date
import calendar as _cal
import pytz
from strategy.config import TIMEZONE, AUTO_CLOSE_HOUR, AUTO_CLOSE_MINUTE

def _to_taipei(ts: datetime) -> datetime:
    tz = pytz.timezone(TIMEZONE)
    if ts.tzinfo is None:
        return tz.localize(ts)
    return ts.astimezone(tz)

def is_third_wed_1329(ts: datetime) -> bool:
    """是否為台北時間每月第三個星期三 13:29。"""
    local = _to_taipei(ts)
    if not (local.hour == AUTO_CLOSE_HOUR and local.minute == AUTO_CLOSE_MINUTE):
        return False
    y, m = local.year, local.month
    cal = _cal.monthcalendar(y, m)  # 5x7
    # 找當月所有星期三（週一為 0）
    weds = [week[_cal.WEDNESDAY] for week in cal if week[_cal.WEDNESDAY] != 0]
    if len(weds) < 3:
        return False
    third = date(y, m, weds[2])
    return local.date() == third
