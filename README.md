# Hermes Capability

Hermes Agent 的交易能力成果儀表板。

## 你能在這裡看到什麼

| 區塊 | 說明 |
|------|------|
| 📊 今日市場判斷 | 趨勢方向、關鍵位、量價分析、決策 |
| 💰 紙交易績效 | 已實現/未實現 PnL、持倉、勝率 |
| 🎯 點餐任務 | 當前任務狀態、目標金額、結果 |
| 📚 學習進度 | 近期學到的新知識、更新了哪些框架 |
| 🔮 預測記錄 | Brier Score、預測到期檢查 |

## 架構

```
├── index.html          # 成果儀表板（GitHub Pages）
├── trade.py            # 主動交易 CLI
├── monitor.py          # 即時 TP/SL 監控
├── predictions.json    # 預測記錄
├── config.json         # 設定
├── .github/workflows/
│   ├── summary.yml     # 每小時更新摘要
│   └── monitor.yml     # 每 5 分鐘檢查 TP/SL
└── README.md
```

## 點餐任務

Hermes 的動態能力測試。你點餐 → 我查價 → 4 小時內用交易賺到餐費。

狀態查詢：`https://hsiao0809.github.io/hermes-capability/`
