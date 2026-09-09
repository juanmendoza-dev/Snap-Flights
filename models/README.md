# models

Prediction over the snapshot store. Nothing here fetches or writes fares — it reads what
`pipeline/store/` wrote.

| Directory | Owns |
|-----------|------|
| `features/` | Feature builders that read from the snapshot store (advance-purchase buckets, seasonality, day-of-week). |
| `baseline/` | The percentile / seasonality model behind buy-vs-wait (E2, SF-06). |
| `backtest/` | The backtesting harness and its reports — hit rate and regret against held-out history. |

Every number a model produces must be traceable back to rows in the snapshot store (E2).
