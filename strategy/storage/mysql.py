# -*- coding: utf-8 -*-
import pandas as pd
from sqlalchemy import create_engine, text
from strategy.config import MYSQL_URL

def _table_from_symbol(symbol_prefix: str) -> str:
    s = symbol_prefix.upper()
    if s.startswith("TXF"):
        return "ticks_TXF"
    if s.startswith("MXF"):
        return "ticks_MXF"
    return f"ticks_{s}"

def load_history(symbol_prefix: str,
                 limit_bars: int = 100_000,
                 frame: str = "1min",
                 start_ts: str | None = None,
                 end_ts: str | None = None,
                 only_day: bool = True) -> pd.DataFrame:
    if frame.lower() not in ("1min", "1m"):
        raise ValueError("loader 目前僅支援 1min（由 ticks_* 聚合），再由程式聚合成 1H。")
    table = _table_from_symbol(symbol_prefix)
    eng = create_engine(MYSQL_URL)

    where_parts = []
    params = {"lim": int(limit_bars)}
    if start_ts:
        where_parts.append("`timestamp` >= :start_ts")
        params["start_ts"] = start_ts
    if end_ts:
        where_parts.append("`timestamp` < :end_ts")
        params["end_ts"] = end_ts
    if only_day:
        where_parts.append("TIME(`timestamp`) BETWEEN '08:45:00' AND '13:45:00'")
    where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    sql = text(f"""
        SELECT
          FROM_UNIXTIME(UNIX_TIMESTAMP(`timestamp`) - MOD(UNIX_TIMESTAMP(`timestamp`), 60)) AS ts,
          SUBSTRING_INDEX(GROUP_CONCAT(`open`  ORDER BY `timestamp` ASC  SEPARATOR ','), ',', 1) AS o,
          MAX(`high`) AS h,
          MIN(`low`)  AS l,
          SUBSTRING_INDEX(GROUP_CONCAT(`close` ORDER BY `timestamp` DESC SEPARATOR ','), ',', 1) AS c,
          SUM(`volume`) AS v
        FROM {table}
        {where_sql}
        GROUP BY ts
        ORDER BY ts ASC
        LIMIT :lim
    """)

    with eng.begin() as conn:
        df = pd.read_sql(sql, conn, params=params)

    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"])
        for col in ("o","h","l","c"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["v"] = pd.to_numeric(df["v"], errors="coerce").fillna(0).astype("int64")

    return df


from sqlalchemy import create_engine, text  # ensure symbols available in this scope

def load_hourly_from_ticks(symbol_prefix: str,
                           hours: int = 200,
                           start_ts: str | None = None,
                           end_ts: str | None = None,
                           only_day: bool = True) -> pd.DataFrame:
    """從 ticks_* 聚合成 1H K（ts,o,h,l,c,v）。"""
    table = _table_from_symbol(symbol_prefix)
    eng = create_engine(MYSQL_URL)

    where_parts, params = [], {}
    if start_ts:
        where_parts.append("`timestamp` >= :start_ts"); params["start_ts"] = start_ts
    if end_ts:
        where_parts.append("`timestamp` < :end_ts"); params["end_ts"] = end_ts
    if only_day:
        where_parts.append("TIME(`timestamp`) BETWEEN '08:45:00' AND '13:45:00'")
    where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    sql = text(f"""
    WITH m1 AS (
      SELECT
        FROM_UNIXTIME(UNIX_TIMESTAMP(`timestamp`) - MOD(UNIX_TIMESTAMP(`timestamp`), 60)) AS m_ts,
        SUBSTRING_INDEX(GROUP_CONCAT(`open`  ORDER BY `timestamp` ASC  SEPARATOR ','), ',', 1) AS o,
        MAX(`high`) AS h,
        MIN(`low`)  AS l,
        SUBSTRING_INDEX(GROUP_CONCAT(`close` ORDER BY `timestamp` DESC SEPARATOR ','), ',', 1) AS c,
        SUM(`volume`) AS v
      FROM {table}
      {where_sql}
      GROUP BY m_ts
    )
    SELECT
      FROM_UNIXTIME(UNIX_TIMESTAMP(m_ts) - MOD(UNIX_TIMESTAMP(m_ts), 3600)) AS ts,
      SUBSTRING_INDEX(GROUP_CONCAT(o ORDER BY m_ts ASC  SEPARATOR ','), ',', 1) AS o,
      MAX(h) AS h,
      MIN(l) AS l,
      SUBSTRING_INDEX(GROUP_CONCAT(c ORDER BY m_ts DESC SEPARATOR ','), ',', 1) AS c,
      SUM(v) AS v
    FROM m1
    GROUP BY ts
    ORDER BY ts ASC
    """)
    with eng.begin() as conn:
        df = pd.read_sql(sql, conn, params=params)

    if hours and not (start_ts or end_ts):
        df = df.tail(int(hours))

    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"])
        for col in ("o","h","l","c"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["v"] = pd.to_numeric(df["v"], errors="coerce").fillna(0).astype("int64")
    return df
