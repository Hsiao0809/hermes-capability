#!/usr/bin/env python3
"""
trade.py — Hermes 主動紙交易 CLI

使用方式：
  python3 trade.py long SYMBOL --entry PRICE --sl STOP --tp1 TARGET1 --tp2 TARGET2 --risk USDT
  python3 trade.py short SYMBOL --entry PRICE --sl STOP --tp1 TARGET1 --tp2 TARGET2 --risk USDT
  python3 trade.py close TRADE_ID
  python3 trade.py list

範例：
  python3 trade.py long BTCUSDT --entry 80500 --sl 79500 --tp1 83000 --tp2 85000 --risk 10
"""

import json
import os
import sys
import argparse
from datetime import datetime, timezone, timedelta
import urllib.request

CST = timezone(timedelta(hours=8))
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
TRADES_FILE = os.path.join(DATA_DIR, "paper_trades.json")

os.makedirs(DATA_DIR, exist_ok=True)

def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

def load_trades():
    if not os.path.exists(TRADES_FILE):
        return {"trades": [], "stats": {"total_realized_pnl_usdt": 0.0, "total_unrealized_pnl_usdt": 0.0, "max_drawdown_usdt": 0.0, "total_trades": 0, "winning_trades": 0, "losing_trades": 0}}
    with open(TRADES_FILE) as f:
        return json.load(f)

def save_trades(data):
    with open(TRADES_FILE, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_current_price(symbol):
    """Fetch live price from Binance public API."""
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            return float(data['price'])
    except Exception as e:
        print(f"⚠️  Failed to fetch price for {symbol}: {e}", file=sys.stderr)
        return None

def open_trade(args):
    cfg = load_config()
    trades_data = load_trades()
    trades = trades_data["trades"]

    # Check max positions
    open_trades = [t for t in trades if t.get("status") == "open"]
    max_pos = cfg["account"]["max_positions"]
    if len(open_trades) >= max_pos:
        print(f"❌ 已達最大持倉數量 ({max_pos})，無法開新單")
        return False

    # Calculate position size
    risk_usdt = args.risk
    sl_pct = abs(float(args.sl) - float(args.entry)) / float(args.entry)
    position_size = risk_usdt / sl_pct  # in USDT notional

    trade_id = f"PT-{datetime.now(CST).strftime('%Y%m%d-%H%M%S')}-{args.symbol}"

    trade = {
        "id": trade_id,
        "symbol": args.symbol,
        "side": args.side.upper(),
        "entry_price": float(args.entry),
        "stop_loss": float(args.sl),
        "take_profit_1": float(args.tp1) if args.tp1 else None,
        "take_profit_2": float(args.tp2) if args.tp2 else None,
        "position_size_usdt": round(position_size, 2),
        "risk_usdt": risk_usdt,
        "status": "open",
        "opened_at": datetime.now(CST).isoformat(),
        "closed_at": None,
        "realized_pnl_usdt": 0.0,
        "realized_pnl_pct": 0.0,
        "unrealized_pnl_usdt": 0.0,
        "unrealized_pnl_pct": 0.0,
        "max_unrealized_pnl_usdt": 0.0,
        "max_unrealized_pnl_pct": 0.0,
        "min_unrealized_pnl_usdt": 0.0,
        "min_unrealized_pnl_pct": 0.0,
        "take_profit_1_hit": False,
        "take_profit_2_hit": False,
        "stop_loss_hit": False,
        "time_stop_expired": False,
        "exit_reason": None,
        "notes": args.notes or ""
    }
    trades.append(trade)
    trades_data["stats"]["total_trades"] += 1
    save_trades(trades_data)

    print(f"✅ 開單成功:")
    print(f"   ID:     {trade_id}")
    print(f"   方向:   {'📈 做多' if trade['side'] == 'LONG' else '📉 做空'}")
    print(f"   幣種:   {trade['symbol']}")
    print(f"   進場:   {trade['entry_price']}")
    print(f"   停損:   {trade['stop_loss']} ({sl_pct*100:.1f}%)")
    if trade['take_profit_1']:
        tp1_pct = abs(trade['take_profit_1'] - trade['entry_price']) / trade['entry_price'] * 100
        print(f"   停利 1: {trade['take_profit_1']} (+{tp1_pct:.1f}%)")
    if trade['take_profit_2']:
        tp2_pct = abs(trade['take_profit_2'] - trade['entry_price']) / trade['entry_price'] * 100
        print(f"   停利 2: {trade['take_profit_2']} (+{tp2_pct:.1f}%)")
    print(f"   風險:   {risk_usdt} USDT")
    print(f"   部位:   {position_size:.2f} USDT")
    return True

def close_trade(trade_id, exit_price=None, reason="manual"):
    trades_data = load_trades()
    trades = trades_data["trades"]

    for trade in trades:
        if trade["id"] == trade_id and trade["status"] == "open":
            # Get current price if not provided
            if exit_price is None:
                price = get_current_price(trade["symbol"])
                if price is None:
                    print(f"❌ 無法取得即時價格，請指定 exit_price")
                    return False
                exit_price = price

            # Calculate PnL
            if trade["side"] == "LONG":
                pnl_pct = (exit_price - trade["entry_price"]) / trade["entry_price"]
            else:
                pnl_pct = (trade["entry_price"] - exit_price) / trade["entry_price"]

            pnl_usdt = pnl_pct * trade["position_size_usdt"]

            trade["status"] = "closed"
            trade["closed_at"] = datetime.now(CST).isoformat()
            trade["exit_price"] = exit_price
            trade["realized_pnl_usdt"] = round(pnl_usdt, 2)
            trade["realized_pnl_pct"] = round(pnl_pct * 100, 2)
            trade["exit_reason"] = reason

            # Update stats
            trades_data["stats"]["total_realized_pnl_usdt"] = round(
                trades_data["stats"]["total_realized_pnl_usdt"] + pnl_usdt, 2)

            if pnl_usdt > 0:
                trades_data["stats"]["winning_trades"] += 1
            else:
                trades_data["stats"]["losing_trades"] += 1

            save_trades(trades_data)

            emoji = "✅" if pnl_usdt > 0 else "❌"
            print(f"{emoji} 平倉成功:")
            print(f"   ID:     {trade['id']}")
            print(f"   出場價: {exit_price}")
            print(f"   損益:   {'+' if pnl_usdt >= 0 else ''}{pnl_usdt:.2f} USDT ({pnl_pct*100:+.2f}%)")
            print(f"   原因:   {reason}")
            return True

    print(f"❌ 找不到持倉中的交易: {trade_id}")
    return False

def list_trades():
    trades_data = load_trades()
    trades = trades_data["trades"]

    if not trades:
        print("📭 尚無交易記錄")
        return

    open_trades = [t for t in trades if t["status"] == "open"]
    closed_trades = [t for t in trades if t["status"] == "closed"]

    print(f"📊 總交易: {len(trades)} | 持倉: {len(open_trades)} | 已平倉: {len(closed_trades)}")
    print(f"   已實現 PnL: {trades_data['stats']['total_realized_pnl_usdt']:+.2f} USDT")
    total = trades_data['stats']['winning_trades'] + trades_data['stats']['losing_trades']
    if total > 0:
        win_rate = trades_data['stats']['winning_trades'] / total * 100
        print(f"   勝率: {trades_data['stats']['winning_trades']}/{total} ({win_rate:.0f}%)")

    if open_trades:
        print(f"\n📈 持倉中:")
        print(f"{'ID':<35} {'幣種':<12} {'方向':<6} {'進場':<12} {'浮動 PnL':<12} {'最大漲幅':<12} {'最大回撤':<12}")
        print("-" * 100)
        for t in open_trades:
            price = get_current_price(t["symbol"])
            if price:
                if t["side"] == "LONG":
                    upnl_pct = (price - t["entry_price"]) / t["entry_price"]
                else:
                    upnl_pct = (t["entry_price"] - price) / t["entry_price"]
                upnl_usdt = upnl_pct * t["position_size_usdt"]
                t["unrealized_pnl_usdt"] = round(upnl_usdt, 2)
                t["unrealized_pnl_pct"] = round(upnl_pct * 100, 2)

                # Track max/min
                if upnl_usdt > t.get("max_unrealized_pnl_usdt", 0):
                    t["max_unrealized_pnl_usdt"] = round(upnl_usdt, 2)
                    t["max_unrealized_pnl_pct"] = round(upnl_pct * 100, 2)
                if upnl_usdt < t.get("min_unrealized_pnl_usdt", 0):
                    t["min_unrealized_pnl_usdt"] = round(upnl_usdt, 2)
                    t["min_unrealized_pnl_pct"] = round(upnl_pct * 100, 2)

            side_emoji = "📈" if t["side"] == "LONG" else "📉"
            upnl_str = f"{t['unrealized_pnl_usdt']:+.2f}" if t.get('unrealized_pnl_usdt') else "N/A"
            max_str = f"{t.get('max_unrealized_pnl_pct', 0):+.1f}%" if t.get('max_unrealized_pnl_pct') else "N/A"
            min_str = f"{t.get('min_unrealized_pnl_pct', 0):+.1f}%" if t.get('min_unrealized_pnl_pct') else "N/A"
            print(f"{t['id'][:33]:<35} {t['symbol']:<12} {side_emoji:<6} {t['entry_price']:<12} {upnl_str:<12} {max_str:<12} {min_str:<12}")

    if closed_trades:
        print(f"\n📜 已平倉:")
        for t in closed_trades[-5:]:
            emoji = "✅" if t["realized_pnl_usdt"] > 0 else "❌"
            print(f"  {emoji} {t['id']} | {t['symbol']} | {t['realized_pnl_usdt']:+.2f} USDT ({t['realized_pnl_pct']:+.2f}%) | {t['exit_reason']}")


def update_prices():
    """Update unrealized PnL for all open trades. Called by monitor.py."""
    trades_data = load_trades()
    trades = trades_data["trades"]

    for trade in trades:
        if trade["status"] != "open":
            continue

        price = get_current_price(trade["symbol"])
        if price is None:
            continue

        if trade["side"] == "LONG":
            pnl_pct = (price - trade["entry_price"]) / trade["entry_price"]
        else:
            pnl_pct = (trade["entry_price"] - price) / trade["entry_price"]

        pnl_usdt = pnl_pct * trade["position_size_usdt"]
        trade["unrealized_pnl_usdt"] = round(pnl_usdt, 2)
        trade["unrealized_pnl_pct"] = round(pnl_pct * 100, 2)

        # Track max profit and max drawdown
        if pnl_usdt > trade.get("max_unrealized_pnl_usdt", 0):
            trade["max_unrealized_pnl_usdt"] = round(pnl_usdt, 2)
            trade["max_unrealized_pnl_pct"] = round(pnl_pct * 100, 2)
        if pnl_usdt < trade.get("min_unrealized_pnl_usdt", 0):
            trade["min_unrealized_pnl_usdt"] = round(pnl_usdt, 2)
            trade["min_unrealized_pnl_pct"] = round(pnl_pct * 100, 2)

    # Calculate total unrealized
    unrealized = sum(t.get("unrealized_pnl_usdt", 0) for t in trades if t["status"] == "open")
    trades_data["stats"]["total_unrealized_pnl_usdt"] = round(unrealized, 2)

    save_trades(trades_data)
    return trades_data


def check_tp_sl():
    """Check all open trades for TP/SL hits. Returns list of closed trade IDs."""
    update_prices()
    trades_data = load_trades()
    trades = trades_data["trades"]
    closed_ids = []

    for trade in trades:
        if trade["status"] != "open":
            continue

        symbol = trade["symbol"]
        price = get_current_price(symbol)
        if price is None:
            continue

        # Check stop loss
        if trade["side"] == "LONG" and price <= trade["stop_loss"]:
            print(f"🔴 停損觸發 {symbol}: {price} <= {trade['stop_loss']}")
            close_trade(trade["id"], exit_price=price, reason="stop_loss")
            closed_ids.append(trade["id"])
            continue
        elif trade["side"] == "SHORT" and price >= trade["stop_loss"]:
            print(f"🔴 停損觸發 {symbol}: {price} >= {trade['stop_loss']}")
            close_trade(trade["id"], exit_price=price, reason="stop_loss")
            closed_ids.append(trade["id"])
            continue

        # Check take profit 2
        if trade["take_profit_2"]:
            if trade["side"] == "LONG" and price >= trade["take_profit_2"]:
                print(f"🟢 停利 2 觸發 {symbol}: {price} >= {trade['take_profit_2']}")
                trade["take_profit_2_hit"] = True
                close_trade(trade["id"], exit_price=price, reason="take_profit_2")
                closed_ids.append(trade["id"])
                continue
            elif trade["side"] == "SHORT" and price <= trade["take_profit_2"]:
                print(f"🟢 停利 2 觸發 {symbol}: {price} <= {trade['take_profit_2']}")
                trade["take_profit_2_hit"] = True
                close_trade(trade["id"], exit_price=price, reason="take_profit_2")
                closed_ids.append(trade["id"])
                continue

        # Check take profit 1 (if TP2 not set)
        if trade["take_profit_1"] and not trade["take_profit_2"]:
            if trade["side"] == "LONG" and price >= trade["take_profit_1"]:
                print(f"🟢 停利 1 觸發 {symbol}: {price} >= {trade['take_profit_1']}")
                trade["take_profit_1_hit"] = True
                close_trade(trade["id"], exit_price=price, reason="take_profit_1")
                closed_ids.append(trade["id"])
                continue
            elif trade["side"] == "SHORT" and price <= trade["take_profit_1"]:
                print(f"🟢 停利 1 觸發 {symbol}: {price} <= {trade['take_profit_1']}")
                trade["take_profit_1_hit"] = True
                close_trade(trade["id"], exit_price=price, reason="take_profit_1")
                closed_ids.append(trade["id"])
                continue

        # Check time stop
        from datetime import datetime
        opened = datetime.fromisoformat(trade["opened_at"])
        days_old = (datetime.now(CST) - opened).days
        if days_old >= 7:
            print(f"⏰ 時間停損觸發 {symbol}: 持倉 {days_old} 天")
            close_trade(trade["id"], exit_price=price, reason="time_stop")
            trade["time_stop_expired"] = True
            closed_ids.append(trade["id"])
            continue

    return closed_ids


def main():
    parser = argparse.ArgumentParser(description="Hermes 主動紙交易 CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Long
    long_parser = subparsers.add_parser("long", help="做多")
    long_parser.add_argument("symbol", help="幣種 (e.g. BTCUSDT)")
    long_parser.add_argument("--entry", "-e", required=True, type=float)
    long_parser.add_argument("--sl", "-s", required=True, type=float, help="停損價")
    long_parser.add_argument("--tp1", type=float, help="停利 1")
    long_parser.add_argument("--tp2", type=float, help="停利 2")
    long_parser.add_argument("--risk", "-r", type=float, default=10, help="風險 USDT (default: 10)")
    long_parser.add_argument("--notes", "-n", help="備註")

    # Short
    short_parser = subparsers.add_parser("short", help="做空")
    short_parser.add_argument("symbol", help="幣種 (e.g. BTCUSDT)")
    short_parser.add_argument("--entry", "-e", required=True, type=float)
    short_parser.add_argument("--sl", "-s", required=True, type=float, help="停損價")
    short_parser.add_argument("--tp1", type=float, help="停利 1")
    short_parser.add_argument("--tp2", type=float, help="停利 2")
    short_parser.add_argument("--risk", "-r", type=float, default=10, help="風險 USDT (default: 10)")
    short_parser.add_argument("--notes", "-n", help="備註")

    # Close
    close_parser = subparsers.add_parser("close", help="平倉")
    close_parser.add_argument("trade_id", help="交易 ID")
    close_parser.add_argument("--exit", type=float, help="出場價格 (預設: 即時價格)")

    # List
    subparsers.add_parser("list", help="列出所有交易")

    # Check TP/SL
    subparsers.add_parser("check", help="檢查所有持倉的 TP/SL")

    # Update prices
    subparsers.add_parser("update", help="更新所有持倉的浮動損益")

    args = parser.parse_args()

    if args.command in ("long", "short"):
        args.side = args.command
        return open_trade(args)
    elif args.command == "close":
        return close_trade(args.trade_id, exit_price=args.exit)
    elif args.command == "list":
        return list_trades()
    elif args.command == "check":
        closed = check_tp_sl()
        if closed:
            print(f"平倉 {len(closed)} 筆: {closed}")
        else:
            print("無觸發")
        return True
    elif args.command == "update":
        update_prices()
        print("✅ 浮動損益已更新")
        return True

if __name__ == "__main__":
    main()
