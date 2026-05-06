#!/usr/bin/env python3
"""
summary.py — 每小時更新成果摘要數據 (data/summary.json)

從 paper_trades.json + predictions.json + config.json 生成摘要，
供 index.html 顯示。

使用方式：
  python3 summary.py
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

sys.path.insert(0, BASE_DIR)
from trade import update_prices, get_current_price, load_trades, load_config

def generate():
    cfg = load_config()
    trades_data = load_trades()

    # Update prices first
    update_prices()

    # Reload after update
    trades_data = load_trades()

    open_trades = [t for t in trades_data["trades"] if t["status"] == "open"]
    closed_trades = [t for t in trades_data["trades"] if t["status"] == "closed"]

    # Load predictions
    preds_path = os.path.join(BASE_DIR, "predictions.json")
    predictions = {"predictions": [], "stats": {}}
    if os.path.exists(preds_path):
        with open(preds_path) as f:
            predictions = json.load(f)

    # Build summary
    summary = {
        "updated_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M CST"),
        "updated_at_iso": datetime.now(CST).isoformat(),
        "market": {
            "btc_price": get_current_price("BTCUSDT"),
            "eth_price": get_current_price("ETHUSDT"),
            "judgment": None  # filled by latest analysis if available
        },
        "trading": {
            "total_trades": trades_data["stats"]["total_trades"],
            "open_count": len(open_trades),
            "closed_count": len(closed_trades),
            "realized_pnl": trades_data["stats"]["total_realized_pnl_usdt"],
            "unrealized_pnl": trades_data["stats"]["total_unrealized_pnl_usdt"],
            "winning_trades": trades_data["stats"]["winning_trades"],
            "losing_trades": trades_data["stats"]["losing_trades"],
            "open_positions": [
                {
                    "id": t["id"],
                    "symbol": t["symbol"],
                    "side": "LONG" if t["side"] == "LONG" else "SHORT",
                    "entry": t["entry_price"],
                    "current_pnl": t.get("unrealized_pnl_usdt", 0),
                    "current_pnl_pct": t.get("unrealized_pnl_pct", 0),
                    "max_profit_pct": t.get("max_unrealized_pnl_pct", 0),
                    "max_drawdown_pct": t.get("min_unrealized_pnl_pct", 0),
                }
                for t in open_trades
            ]
        },
        "predictions": {
            "total": predictions["stats"].get("total_predictions", 0),
            "scored": predictions["stats"].get("scored_predictions", 0),
            "avg_brier": predictions["stats"].get("avg_brier_score"),
            "recent": predictions["predictions"][-3:] if predictions["predictions"] else []
        },
        "order_task": {
            "active": cfg.get("order_task", {}).get("active", False),
            "food": cfg.get("order_task", {}).get("food"),
            "target_usdt": cfg.get("order_task", {}).get("target_usdt"),
            "deadline": cfg.get("order_task", {}).get("deadline"),
            "started_at": cfg.get("order_task", {}).get("started_at")
        },
        "recent_closed": [
            {
                "id": t["id"],
                "symbol": t["symbol"],
                "pnl": t["realized_pnl_usdt"],
                "pnl_pct": t["realized_pnl_pct"],
                "reason": t["exit_reason"],
                "closed_at": t["closed_at"]
            }
            for t in closed_trades[-5:]
        ]
    }

    # Write summary
    os.makedirs(DATA_DIR, exist_ok=True)
    summary_path = os.path.join(DATA_DIR, "summary.json")
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"✅ Summary generated: {summary_path}")
    print(f"   Trades: {summary['trading']['total_trades']} total, {summary['trading']['open_count']} open")
    print(f"   Realized: {summary['trading']['realized_pnl']:+.2f} USDT")
    print(f"   Unrealized: {summary['trading']['unrealized_pnl']:+.2f} USDT")
    return summary

if __name__ == "__main__":
    generate()
