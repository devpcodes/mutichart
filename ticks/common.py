import redis
from sqlalchemy import create_engine, text
from config import REDIS_HOST, REDIS_PORT, MYSQL_URL

def get_redis():
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

def get_mysql_engine():
    return create_engine(MYSQL_URL)

def ensure_tables(engine):
    sql_mxf = """
    CREATE TABLE IF NOT EXISTS ticks_MXF (
        timestamp DATETIME NOT NULL,
        contract VARCHAR(20) NOT NULL,
        open FLOAT,
        high FLOAT,
        low FLOAT,
        close FLOAT,
        volume INT,
        simtrade INT,
        PRIMARY KEY (timestamp, contract)
    );
    """
    sql_txf = """
    CREATE TABLE IF NOT EXISTS ticks_TXF (
        timestamp DATETIME NOT NULL,
        contract VARCHAR(20) NOT NULL,
        open FLOAT,
        high FLOAT,
        low FLOAT,
        close FLOAT,
        volume INT,
        simtrade INT,
        PRIMARY KEY (timestamp, contract)
    );
    """
    with engine.begin() as conn:
        conn.execute(text(sql_mxf))
        conn.execute(text(sql_txf))
