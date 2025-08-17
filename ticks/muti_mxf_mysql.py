import pandas as pd
from sqlalchemy import create_engine, Table, MetaData
from sqlalchemy.dialects.mysql import insert
from datetime import datetime

# === 配置 ===
CSV_PATH = "MXF1 1 分鐘.csv"
MYSQL_URL = "mysql+pymysql://trader:traderpass@localhost:3307/market"
TABLE_NAME = "ticks_MXF"
CHUNK_SIZE = 50000
CUTOFF_TIME = datetime(2025, 8, 4, 13, 17, 4)

# === MySQL 連線 ===
engine = create_engine(MYSQL_URL)
meta = MetaData()
meta.reflect(bind=engine)
table = Table(TABLE_NAME, meta, autoload_with=engine)

def upsert_batch(conn, df):
    if df.empty:
        return
    data_dicts = df.to_dict(orient='records')
    insert_stmt = insert(table).values(data_dicts)
    upsert_stmt = insert_stmt.on_duplicate_key_update(
        {c.name: insert_stmt.inserted[c.name]
         for c in table.columns
         if c.name not in table.primary_key.columns}
    )
    conn.execute(upsert_stmt)

chunks = pd.read_csv(CSV_PATH, chunksize=CHUNK_SIZE)
total_rows = 0
with engine.begin() as conn:
    for chunk in chunks:
        # 清理欄位名稱
        chunk.columns = chunk.columns.str.strip().str.replace('<','').str.replace('>','')

        # 時間處理
        chunk['timestamp'] = pd.to_datetime(chunk['Date'] + ' ' + chunk['Time'])
        chunk = chunk[chunk['timestamp'] <= CUTOFF_TIME]
        if chunk.empty:
            continue

        # 固定欄位
        chunk['contract'] = 'MXF'
        chunk['simtrade'] = 0

        # 欄位重新命名
        chunk.rename(columns={
            'Open': 'open',
            'High': 'high',
            'Low': 'low',
            'Close': 'close',
            'Volume': 'volume'
        }, inplace=True)
        chunk = chunk[['timestamp', 'contract', 'open', 'high', 'low', 'close', 'volume', 'simtrade']]

        # 寫入 MySQL
        upsert_batch(conn, chunk)
        total_rows += len(chunk)
        print(f"已處理 {total_rows} 筆...")

print(f"匯入完成，共 {total_rows} 筆（只到 {CUTOFF_TIME}）。")
