#!/usr/bin/env python3
"""
monitor.py — 即時 TP/SL 監控

每 N 分鐘執行一次，檢查所有持倉是否觸發停損/停利/時間停損。
觸發時自動平倉，並輸出摘要。

使用方式：
  python3 monitor.py                        # 單次檢查
  python3 monitor.py --loop --interval 300  # 每 5 分鐘循環檢查
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Import trade functions
sys.path.insert(0, BASE_DIR)
import importlib.util
spec = importlib.util.spec_from_file_location("trade", os.path.join(BASE_DIR, "trade.py"))
trade_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trade_mod)

def run_check():
    """Single check cycle. Returns summary dict."""
    timestamp = datetime.now(CST).isoformat()

    # Update prices and check TP/SL
    closed_ids = trade_mod.check_tp_sl()
    trades_data = trade_mod.load_trades()
    open_trades = [t for t in trades_data["trades"] if t["status"] == "open"]

    summary = {
        "timestamp": timestamp,
        "open_trades": len(open_trades),
        "closed_this_cycle": len(closed_ids),
        "closed_ids": closed_ids,
        "total_realized_pnl": trades_data["stats"]["total_realized_pnl_usdt"],
        "total_unrealized_pnl": trades_data["stats"]["total_unrealized_pnl_usdt"],
        "open_details": []
    }

    for t in open_trades:
        summary["open_details"].append({
            "id": t["id"],
            "symbol": t["symbol"],
            "side": t["side"],
            "entry": t["entry_price"],
            "unrealized_pnl": t.get("unrealized_pnl_usdt", 0),
            "unrealized_pnl_pct": t.get("unrealized_pnl_pct", 0)
        })

    return summary

def print_summary(summary):
    print(f"\n{'='*50}")
    print(f"📊 Hermes Monitor — {summary['timestamp']}")
    print(f"{'='*50}")
    print(f"持倉: {summary['open_trades']} 筆")
    print(f"本輪平倉: {summary['closed_this_cycle']} 筆 {summary['closed_ids']}")
    print(f"已實現 PnL: {summary['total_realized_pnl']:+.2f} USDT")
    print(f"未實現 PnL: {summary['total_unrealized_pnl']:+.2f} USDT")

    if summary["open_details"]:
        print(f"\n持倉明細:")
        for t in summary["open_details"]:
            side_emoji = "📈" if t["side"] == "LONG" else "📉"
            print(f"  {side_emoji} {t['symbol']} | 進場: {t['entry']} | 浮動: {t['unrealized_pnl']:+.2f} ({t['unrealized_pnl_pct']:+.2f}%)")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    # Check for --loop
    if "--loop" in sys.argv:
        try:
            idx = sys.argv.index("--interval")
            interval = int(sys.argv[idx + 1])
        except (ValueError, IndexError):
            interval = 300  # default 5 min

        print(f"🔄 Monitor starting — checking every {interval}s")
        while True:
            summary = run_check()
            print_summary(summary)
            time.sleep(interval)
    else:
        summary = run_check()
        print_summary(summary)
