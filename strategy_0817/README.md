# PSAR 小時K + 即時反轉（實盤/回測整合版）

- 小時K封口依 Parabolic SAR 產生反手訊號
- tick 級即時：若價格穿越當前 SAR 立刻反手
- 回測：以 1 分鐘 K 近似 tick；聚合成 1 小時 K 做決策
- 每月第三個星期三 13:29（台北時間）自動平倉（回測/實盤皆生效）

## 使用
- 回測（預設產生 MXF 的單商品結果）
  ```bash
  python -m strategy.run_backtest
  ```
  或指定 TXF：
  ```bash
  python -m strategy.run_backtest --symbol TXF
  ```

- 實盤（需 Redis pubsub 推送 tick；訊息格式：
  `{"symbol":"TXF","timestamp":"2025-08-05T09:00:01","price":23123,"vol":1}`）
  ```bash
  python -m strategy.run_live
  ```

## MySQL 資料
回測直接從 `ticks_TXF` / `ticks_MXF` 聚合成 1min K，欄位需求：
`timestamp, contract, open, high, low, close, volume`。

## 參數
於 `strategy/config.py` 調整：
- `STRATEGY="sar_psar_hourly"`
- `STRATEGY_PARAMS`: `af`（加速因子）、`af_max`、`qty` 等。
