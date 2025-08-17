import json
import pandas as pd
import schedule
import time
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.orm import sessionmaker
from common import get_redis, get_mysql_engine, ensure_tables

# === Redis & MySQL 連線 ===
r = get_redis()
engine = get_mysql_engine()
Session = sessionmaker(bind=engine)
session = Session()

# === UPSERT 寫入方法 ===
def upsert(table, conn, keys, data_iter):
    """
    使用 MySQL 的 ON DUPLICATE KEY UPDATE 避免主鍵衝突
    """
    table = table.table
    insert_stmt = insert(table).values(list(data_iter))
    update_stmt = insert_stmt.on_duplicate_key_update(
        {col.name: insert_stmt.inserted[col.name] for col in table.columns if col.name not in table.primary_key.columns}
    )
    conn.execute(update_stmt)

# === 主要寫入流程 ===
def transfer_data(batch_size=5000):
    ensure_tables(engine)
    keys = r.keys("ticks:*")
    total_inserted = 0

    for key in keys:
        symbol = key.split("ticks:")[1]
        table_name = "ticks_MXF" if symbol.startswith("MXF") else "ticks_TXF"

        data = []
        for _ in range(batch_size):
            tick = r.rpop(key)
            if tick:
                tick_json = json.loads(tick)
                tick_json["contract"] = tick_json.pop("symbol", symbol)
                data.append(tick_json)
            else:
                break

        if not data:
            print(f"[MySQL] {symbol} 無新資料")
            continue

        # DataFrame 處理
        df = pd.DataFrame(data)
        # 去重 (避免同一批資料有重複)
        df.drop_duplicates(subset=["timestamp", "contract"], inplace=True)

        # 寫入 MySQL (UPSERT)
        df.to_sql(
            name=table_name,
            con=engine,
            if_exists="append",
            index=False,
            method=upsert
        )
        print(f"[MySQL] {table_name} UPSERT {len(df)} 筆")
        total_inserted += len(df)

    print(f"[INFO] 本輪同步完成，共寫入 {total_inserted} 筆")

# === 定時排程 ===
schedule.every(1).minutes.do(transfer_data)

print("=== Writer 啟動 (UPSERT + 分表) ===")
while True:
    schedule.run_pending()
    time.sleep(1)
