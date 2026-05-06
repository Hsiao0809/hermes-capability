#!/usr/bin/env python3
"""
trade.py — Hermes 主動紙交易 CLI v2

使用方式：
  python3 trade.py long SYMBOL --entry PRICE --sl STOP --tp1 TARGET1 --tp2 TARGET2 --risk USDT --leverage 1
  python3 trade.py short SYMBOL --entry PRICE --sl STOP --tp1 TARGET1 --tp2 TARGET2 --risk USDT
  python3 trade.py close TRADE_ID [--exit PRICE]
  python3 trade.py list
  python3 trade.py balance
  python3 trade.py price SYMBOL

支援標的格式（Binance USDⓈ-M Futures）：
  - 加密貨幣：BTCUSDT, ETHUSDT, STORJUSDT 等
  - TradFi 美股：AAPL, AMZN, AVGO, BABA, COIN, GOOGL, HOOD, INTC, META, MSFT, MSTR, MU, NVDA, PAYP, PLTR, TSLA, TSM 等
  - TradFi ETF：QQQ, SPY, EWY, EWJ
  - 商品：XAU（黃金）, XAG（白銀）, CL（原油）, NATGAS（天然氣）, COPPER 等

本金：300 USDT 初始（無槓桿預設，可開到 5x）
"""

import json
import os
import sys
import argparse
import re
from datetime import datetime, timezone, timedelta
import urllib.request

CST = timezone(timedelta(hours=8))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
TRADES_FILE = os.path.join(DATA_DIR, "paper_trades.json")

os.makedirs(DATA_DIR, exist_ok=True)


# ═══════════════════════════════════════════════
# Price fetching
# ═══════════════════════════════════════════════

def get_price(symbol):
    """Fetch live price for any supported symbol type.
    
    All symbols are Binance USDⓈ-M futures:
    - Crypto: BTCUSDT, ETHUSDT, STORJUSDT
    - TradFi (TRADIFI_PERPETUAL): COINUSDT, NVDAUSDT, TSLAUSDT, MSTRUSDT, etc.
    """
    symbol = symbol.upper().strip()
    
    # Binance futures API (unified — covers both crypto and TradFi)
    return get_binance_futures_price(symbol)


def get_binance_futures_price(symbol):
    """Fetch price from Binance USDⓈ-M Futures public API."""
    # Ensure USDT suffix
    if not symbol.endswith('USDT'):
        symbol = symbol + 'USDT'
    try:
        url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            return float(data['price'])
    except Exception as e:
        # Fallback to spot API for spot-only pairs
        try:
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
                return float(data['price'])
        except Exception:
            raise ValueError(f"Binance price fetch failed for {symbol}: {e}")


def get_tw_stock_price(symbol):
    """Fetch Taiwan stock price from Yahoo Finance (no API key needed)."""
    ticker = symbol.replace('.TW', '.TW')
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=1d"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            meta = data['chart']['result'][0]['meta']
            return float(meta['regularMarketPrice'])
    except Exception as e:
        raise ValueError(f"TW stock price fetch failed for {symbol}: {e}")


def get_us_stock_price(symbol):
    """Fetch US stock price from Yahoo Finance."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1d"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            meta = data['chart']['result'][0]['meta']
            return float(meta['regularMarketPrice'])
    except Exception as e:
        raise ValueError(f"US stock price fetch failed for {symbol}: {e}")


# ═══════════════════════════════════════════════
# Config & Trades data
# ═══════════════════════════════════════════════

def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def load_trades():
    if not os.path.exists(TRADES_FILE):
        return {
            "trades": [],
            "stats": {
                "total_realized_pnl_usdt": 0.0,
                "total_unrealized_pnl_usdt": 0.0,
                "max_drawdown_usdt": 0.0,
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0
            }
        }
    with open(TRADES_FILE) as f:
        return json.load(f)


def save_trades(data):
    with open(TRADES_FILE, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def update_available_balance():
    """Calculate available balance: initial + realized PnL - open position risk."""
    cfg = load_config()
    trades_data = load_trades()
    initial = cfg['account']['initial_balance_usdt']
    realized = trades_data['stats']['total_realized_pnl_usdt']

    # Open trades still have risk locked
    open_risk = 0
    for t in trades_data['trades']:
        if t['status'] == 'open':
            open_risk += t.get('risk_usdt', 0)

    available = initial + realized - open_risk
    cfg['account']['available_balance_usdt'] = round(available, 2)
    cfg['account']['paper_balance_usdt'] = round(initial + realized, 2)
    save_config(cfg)
    return available


# ═══════════════════════════════════════════════
# Trade actions
# ═══════════════════════════════════════════════

def open_trade(args):
    cfg = load_config()
    trades_data = load_trades()
    trades = trades_data["trades"]

    # Build symbol
    symbol = args.symbol.upper().strip()

    # Check max positions
    open_trades = [t for t in trades if t["status"] == "open"]
    max_pos = cfg["account"]["max_positions"]
    if len(open_trades) >= max_pos:
        print(f"❌ 已達最大持倉數量 ({max_pos})，無法開新單")
        return False

    # Get live price to verify entry
    try:
        live_price = get_price(symbol)
    except ValueError as e:
        print(f"❌ 無法取得 {symbol} 價格: {e}")
        return False

    # Entry validation
    entry = float(args.entry)
    slippage_pct = abs(entry - live_price) / live_price * 100
    if slippage_pct > 2.0:
        print(f"⚠️  進場價 {entry} 偏離當前市價 {live_price} 達 {slippage_pct:.1f}%")
        print(f"   建議使用當前市價 {live_price} 作為進場價")
        confirm = input(f"   仍然使用 {entry}? (y/N): ")
        if confirm.lower() != 'y':
            return False

    # Leverage
    leverage = getattr(args, 'leverage', 1)
    if leverage > cfg['account']['max_leverage']:
        print(f"❌ 槓桿 {leverage}x 超過上限 {cfg['account']['max_leverage']}x")
        return False

    # Check available balance
    available = update_available_balance()
    risk_usdt = float(args.risk)

    if risk_usdt > available:
        print(f"❌ 風險 {risk_usdt} USDT 超過可用餘額 {available:.2f} USDT")
        return False

    if risk_usdt > cfg['account']['max_risk_per_trade']:
        print(f"❌ 風險 {risk_usdt} USDT 超過單筆上限 {cfg['account']['max_risk_per_trade']} USDT")
        return False

    # Calculate position size
    sl_pct = abs(float(args.sl) - entry) / entry
    if sl_pct == 0:
        print("❌ 停損價與進場價相同")
        return False

    position_notional = (risk_usdt / sl_pct) * leverage  # leveraged notional
    position_size = position_notional / entry  # in units

    trade_id = f"PT-{datetime.now(CST).strftime('%Y%m%d-%H%M%S')}-{symbol.replace('.','')}"

    trade = {
        "id": trade_id,
        "symbol": symbol,
        "side": args.side.upper(),
        "entry_price": entry,
        "stop_loss": float(args.sl),
        "take_profit_1": float(args.tp1) if args.tp1 else None,
        "take_profit_2": float(args.tp2) if args.tp2 else None,
        "leverage": leverage,
        "position_size": round(position_size, 6),
        "position_notional_usdt": round(position_notional, 2),
        "risk_usdt": risk_usdt,
        "asset_type": "crypto",
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
    update_available_balance()

    # Classify for display — Binance USDⓈ-M Futures TradFi:
    # Stocks (19): AAPL, AMZN, AVGO, BABA, COIN, CRCL, GOOGL, HOOD, INTC, META, 
    #              MSFT, MSTR, MU, NVDA, PAYP, PLTR, TSLA, TSM, SNDK
    # ETFs (4): QQQ, SPY, EWY, EWJ
    # Commodities (8): XAU, XAG, CL, BZ, NATGAS, COPPER, XPT, XPD
    # Pending (3): AMD, QCOM, USAR
    TRADIFI_SYMBOLS = {
        'AAPL', 'AMZN', 'AVGO', 'BABA', 'COIN', 'CRCL', 'GOOGL', 'HOOD', 'INTC',
        'META', 'MSFT', 'MSTR', 'MU', 'NVDA', 'PAYP', 'PLTR', 'TSLA', 'TSM', 'SNDK',
        'QQQ', 'SPY', 'EWY', 'EWJ',
        'XAU', 'XAG', 'CL', 'BZ', 'NATGAS', 'COPPER', 'XPT', 'XPD',
        'AMD', 'QCOM', 'USAR'
    }
    base = symbol.replace('USDT', '')
    market_type = "🏢 TradFi" if base in TRADIFI_SYMBOLS else "🪙 加密"

    print(f"✅ 開單成功:")
    print(f"   ID:     {trade_id}")
    print(f"   市場:   {market_type}")
    print(f"   標的:   {symbol}")
    print(f"   方向:   {'📈 做多' if trade['side'] == 'LONG' else '📉 做空'}")
    print(f"   進場:   {entry} (市價 {live_price})")
    print(f"   槓桿:   {leverage}x")
    print(f"   停損:   {trade['stop_loss']} ({sl_pct*100:.1f}%)")
    if trade['take_profit_1']:
        tp1_pct = abs(trade['take_profit_1'] - entry) / entry * 100
        print(f"   停利 1: {trade['take_profit_1']} ({tp1_pct:+.1f}%)")
    if trade['take_profit_2']:
        tp2_pct = abs(trade['take_profit_2'] - entry) / entry * 100
        print(f"   停利 2: {trade['take_profit_2']} ({tp2_pct:+.1f}%)")
    print(f"   風險:   {risk_usdt} USDT")
    print(f"   名目部位: {trade['position_notional_usdt']:.2f} USDT ({trade['position_size']} units)")
    print(f"   可用餘額: {update_available_balance():.2f} USDT")
    return True


def close_trade(trade_id, exit_price=None, reason="manual"):
    trades_data = load_trades()
    trades = trades_data["trades"]

    for trade in trades:
        if trade["id"] == trade_id and trade["status"] == "open":
            if exit_price is None:
                try:
                    exit_price = get_price(trade["symbol"])
                except ValueError as e:
                    print(f"❌ 無法取得即時價格: {e}")
                    print(f"   請指定 exit_price，例如: --exit 50000")
                    return False

            # Calculate PnL with leverage
            if trade["side"] == "LONG":
                pnl_pct = (exit_price - trade["entry_price"]) / trade["entry_price"]
            else:
                pnl_pct = (trade["entry_price"] - exit_price) / trade["entry_price"]

            pnl_with_leverage = pnl_pct * trade["leverage"]
            pnl_usdt = pnl_pct * trade["position_notional_usdt"]
            # But actual loss is capped at risk if SL was hit
            if reason == "stop_loss":
                pnl_usdt = max(pnl_usdt, -trade["risk_usdt"])
                pnl_with_leverage = pnl_usdt / trade["position_notional_usdt"]

            trade["status"] = "closed"
            trade["closed_at"] = datetime.now(CST).isoformat()
            trade["exit_price"] = exit_price
            trade["realized_pnl_usdt"] = round(pnl_usdt, 2)
            trade["realized_pnl_pct"] = round(pnl_with_leverage * 100, 2)
            trade["exit_reason"] = reason

            # Update stats
            trades_data["stats"]["total_realized_pnl_usdt"] = round(
                trades_data["stats"]["total_realized_pnl_usdt"] + pnl_usdt, 2)

            if pnl_usdt > 0:
                trades_data["stats"]["winning_trades"] += 1
            else:
                trades_data["stats"]["losing_trades"] += 1

            save_trades(trades_data)
            update_available_balance()

            emoji = "✅" if pnl_usdt > 0 else "❌"
            print(f"{emoji} 平倉成功:")
            print(f"   ID:     {trade['id']}")
            print(f"   標的:   {trade['symbol']}")
            print(f"   出場價: {exit_price}")
            print(f"   損益:   {'+' if pnl_usdt >= 0 else ''}{pnl_usdt:.2f} USDT ({pnl_with_leverage*100:+.2f}%)")
            print(f"   槓桿:   {trade['leverage']}x")
            print(f"   原因:   {reason}")
            print(f"   可用餘額: {update_available_balance():.2f} USDT")
            return True

    print(f"❌ 找不到持倉中的交易: {trade_id}")
    return False


def list_trades():
    trades_data = load_trades()
    trades = trades_data["trades"]
    available = update_available_balance()

    if not trades:
        print("📭 尚無交易記錄")
        print(f"\n💰 本金: 300 USDT | 可用: {available:.2f} USDT")
        return

    open_trades = [t for t in trades if t["status"] == "open"]
    closed_trades = [t for t in trades if t["status"] == "closed"]

    cfg = load_config()
    initial = cfg['account']['initial_balance_usdt']
    realized = trades_data['stats']['total_realized_pnl_usdt']
    unrealized = trades_data['stats']['total_unrealized_pnl_usdt']
    total_equity = initial + realized + unrealized

    total = trades_data['stats']['winning_trades'] + trades_data['stats']['losing_trades']
    win_rate = f"{trades_data['stats']['winning_trades']}/{total} ({trades_data['stats']['winning_trades']/total*100:.0f}%)" if total > 0 else "0/0"

    print(f"{'='*60}")
    print(f"  📊 Hermes 紙交易帳戶")
    print(f"{'='*60}")
    print(f"  初始本金:  {initial:.0f} USDT")
    print(f"  已實現 PnL: {realized:+.2f} USDT")
    print(f"  未實現 PnL: {unrealized:+.2f} USDT")
    print(f"  總權益:    {total_equity:.2f} USDT")
    print(f"  可用餘額:  {available:.2f} USDT")
    print(f"  勝率:      {win_rate}")
    print(f"  總交易:    {trades_data['stats']['total_trades']} | 持倉: {len(open_trades)} | 已平倉: {len(closed_trades)}")
    print(f"{'='*60}")

    if open_trades:
        print(f"\n📈 持倉中:")
        header = f"{'ID':<35} {'標的':<14} {'方向':<4} {'槓桿':<4} {'進場':<14} {'浮動 PnL':<14} {'最大漲幅':<10} {'最大回撤':<10}"
        print(header)
        print("-" * len(header))
        for t in open_trades:
            try:
                price = get_price(t["symbol"])
                if t["side"] == "LONG":
                    upnl_pct = (price - t["entry_price"]) / t["entry_price"] * t.get("leverage", 1)
                else:
                    upnl_pct = (t["entry_price"] - price) / t["entry_price"] * t.get("leverage", 1)
                upnl_usdt = upnl_pct * t["position_notional_usdt"]
                t["unrealized_pnl_usdt"] = round(upnl_usdt, 2)
                t["unrealized_pnl_pct"] = round(upnl_pct * 100, 2)

                if upnl_usdt > t.get("max_unrealized_pnl_usdt", 0):
                    t["max_unrealized_pnl_usdt"] = round(upnl_usdt, 2)
                    t["max_unrealized_pnl_pct"] = round(upnl_pct * 100, 2)
                if upnl_usdt < t.get("min_unrealized_pnl_usdt", 0):
                    t["min_unrealized_pnl_usdt"] = round(upnl_usdt, 2)
                    t["min_unrealized_pnl_pct"] = round(upnl_pct * 100, 2)

                save_trades(trades_data)
            except:
                upnl_usdt = 0
                upnl_pct = 0

            side_emoji = "📈" if t["side"] == "LONG" else "📉"
            emoji_str = f"{side_emoji:<4}"
            lev_str = f"{t.get('leverage', 1)}x"
            upnl_str = f"{t.get('unrealized_pnl_usdt', 0):+.2f}"
            max_str = f"{t.get('max_unrealized_pnl_pct', 0):+.1f}%"
            min_str = f"{t.get('min_unrealized_pnl_pct', 0):+.1f}%"
            print(f"{t['id'][:33]:<35} {t['symbol']:<14} {emoji_str} {lev_str:<4} {t['entry_price']:<14} {upnl_str:<14} {max_str:<10} {min_str:<10}")

        # Total unrealized
        total_u = sum(t.get("unrealized_pnl_usdt", 0) for t in open_trades)
        trades_data["stats"]["total_unrealized_pnl_usdt"] = round(total_u, 2)
        save_trades(trades_data)
        print(f"\n  持倉浮動合計: {total_u:+.2f} USDT")

    if closed_trades:
        print(f"\n📜 最近平倉:")
        for t in closed_trades[-5:][::-1]:
            emoji = "✅" if t["realized_pnl_usdt"] > 0 else "❌"
            print(f"  {emoji} {t['symbol']:14s} | {t['realized_pnl_usdt']:+.2f} USDT ({t['realized_pnl_pct']:+.2f}%) | {t['exit_reason']} | {t['closed_at'][:16]}")


def update_prices():
    """Update unrealized PnL for all open trades. Called by monitor.py."""
    trades_data = load_trades()
    trades = trades_data["trades"]

    for trade in trades:
        if trade["status"] != "open":
            continue

        try:
            price = get_price(trade["symbol"])
        except ValueError:
            continue

        lev = trade.get("leverage", 1)
        if trade["side"] == "LONG":
            pnl_pct = (price - trade["entry_price"]) / trade["entry_price"] * lev
        else:
            pnl_pct = (trade["entry_price"] - price) / trade["entry_price"] * lev

        pnl_usdt = pnl_pct * trade["position_notional_usdt"] / lev  # actual pnl = pct * notional / lev
        # Actually: pnl_pct is already leverage-adjusted
        # pnl_usdt should be: (price_change_pct) * notional
        price_change_pct = (price - trade["entry_price"]) / trade["entry_price"]
        if trade["side"] == "SHORT":
            price_change_pct = -price_change_pct
        pnl_usdt = price_change_pct * trade["position_notional_usdt"]

        trade["unrealized_pnl_usdt"] = round(pnl_usdt, 2)
        trade["unrealized_pnl_pct"] = round(pnl_pct, 2)

        if pnl_usdt > trade.get("max_unrealized_pnl_usdt", 0):
            trade["max_unrealized_pnl_usdt"] = round(pnl_usdt, 2)
            trade["max_unrealized_pnl_pct"] = round(pnl_pct, 2)
        if pnl_usdt < trade.get("min_unrealized_pnl_usdt", 0):
            trade["min_unrealized_pnl_usdt"] = round(pnl_usdt, 2)
            trade["min_unrealized_pnl_pct"] = round(pnl_pct, 2)

    unrealized = sum(t.get("unrealized_pnl_usdt", 0) for t in trades if t["status"] == "open")
    trades_data["stats"]["total_unrealized_pnl_usdt"] = round(unrealized, 2)
    save_trades(trades_data)
    update_available_balance()
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

        try:
            price = get_price(trade["symbol"])
        except ValueError:
            continue

        # Check stop loss
        if trade["side"] == "LONG" and price <= trade["stop_loss"]:
            print(f"🔴 停損觸發 {trade['symbol']}: {price} <= {trade['stop_loss']}")
            close_trade(trade["id"], exit_price=price, reason="stop_loss")
            closed_ids.append(trade["id"])
            continue
        elif trade["side"] == "SHORT" and price >= trade["stop_loss"]:
            print(f"🔴 停損觸發 {trade['symbol']}: {price} >= {trade['stop_loss']}")
            close_trade(trade["id"], exit_price=price, reason="stop_loss")
            closed_ids.append(trade["id"])
            continue

        # Check take profit 2
        if trade.get("take_profit_2"):
            if trade["side"] == "LONG" and price >= trade["take_profit_2"]:
                print(f"🟢 停利 2 觸發 {trade['symbol']}: {price} >= {trade['take_profit_2']}")
                trade["take_profit_2_hit"] = True
                close_trade(trade["id"], exit_price=trade["take_profit_2"], reason="take_profit_2")
                closed_ids.append(trade["id"])
                continue
            elif trade["side"] == "SHORT" and price <= trade["take_profit_2"]:
                print(f"🟢 停利 2 觸發 {trade['symbol']}: {price} <= {trade['take_profit_2']}")
                trade["take_profit_2_hit"] = True
                close_trade(trade["id"], exit_price=trade["take_profit_2"], reason="take_profit_2")
                closed_ids.append(trade["id"])
                continue

        # Check take profit 1 (if TP2 not set)
        if trade.get("take_profit_1") and not trade.get("take_profit_2"):
            if trade["side"] == "LONG" and price >= trade["take_profit_1"]:
                print(f"🟢 停利 1 觸發 {trade['symbol']}: {price} >= {trade['take_profit_1']}")
                trade["take_profit_1_hit"] = True
                close_trade(trade["id"], exit_price=trade["take_profit_1"], reason="take_profit_1")
                closed_ids.append(trade["id"])
                continue
            elif trade["side"] == "SHORT" and price <= trade["take_profit_1"]:
                print(f"🟢 停利 1 觸發 {trade['symbol']}: {price} <= {trade['take_profit_1']}")
                trade["take_profit_1_hit"] = True
                close_trade(trade["id"], exit_price=trade["take_profit_1"], reason="take_profit_1")
                closed_ids.append(trade["id"])
                continue

        # Check time stop
        opened = datetime.fromisoformat(trade["opened_at"])
        days_old = (datetime.now(CST) - opened).days
        if days_old >= 7:
            print(f"⏰ 時間停損觸發 {trade['symbol']}: 持倉 {days_old} 天")
            close_trade(trade["id"], exit_price=price, reason="time_stop")
            trade["time_stop_expired"] = True
            closed_ids.append(trade["id"])
            continue

    return closed_ids


def show_balance():
    """Show account balance details."""
    cfg = load_config()
    trades_data = load_trades()
    available = update_available_balance()

    print(f"💰 Hermes 紙交易帳戶")
    print(f"{'='*40}")
    print(f"  初始本金:   {cfg['account']['initial_balance_usdt']:.0f} USDT")
    print(f"  已實現 PnL:  {trades_data['stats']['total_realized_pnl_usdt']:+.2f} USDT")
    print(f"  未實現 PnL:  {trades_data['stats']['total_unrealized_pnl_usdt']:+.2f} USDT")
    print(f"  可用餘額:   {available:.2f} USDT")
    print(f"  最大槓桿:   {cfg['account']['max_leverage']}x")
    print(f"  單筆最大風險: {cfg['account']['max_risk_per_trade']} USDT")


def show_price(symbol):
    """Show live price for a symbol."""
    try:
        price = get_price(symbol)
        market = "🪙 加密" if 'USDT' in symbol else ("🇹🇼 台股" if '.TW' in symbol else "🇺🇸 美股")
        print(f"{market} {symbol}: ${price}")
        return price
    except ValueError as e:
        print(f"❌ {e}")
        return None


# ═══════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Hermes 主動紙交易 CLI v2")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Long
    p = subparsers.add_parser("long", help="做多")
    p.add_argument("symbol")
    p.add_argument("--entry", "-e", required=True, type=float)
    p.add_argument("--sl", "-s", required=True, type=float)
    p.add_argument("--tp1", type=float)
    p.add_argument("--tp2", type=float)
    p.add_argument("--risk", "-r", type=float, default=10)
    p.add_argument("--leverage", "-l", type=int, default=1, help="槓桿倍數 (1-5, default: 1)")
    p.add_argument("--notes", "-n")

    # Short
    p = subparsers.add_parser("short", help="做空")
    p.add_argument("symbol")
    p.add_argument("--entry", "-e", required=True, type=float)
    p.add_argument("--sl", "-s", required=True, type=float)
    p.add_argument("--tp1", type=float)
    p.add_argument("--tp2", type=float)
    p.add_argument("--risk", "-r", type=float, default=10)
    p.add_argument("--leverage", "-l", type=int, default=1, help="槓桿倍數 (1-5, default: 1)")
    p.add_argument("--notes", "-n")

    # Close
    p = subparsers.add_parser("close", help="平倉")
    p.add_argument("trade_id")
    p.add_argument("--exit", type=float)

    # List
    subparsers.add_parser("list", help="列出所有交易")

    # Balance
    subparsers.add_parser("balance", help="顯示帳戶餘額")

    # Price
    p = subparsers.add_parser("price", help="查詢即時價格")
    p.add_argument("symbol")

    # Check TP/SL
    subparsers.add_parser("check", help="檢查所有持倉的 TP/SL")

    # Update
    subparsers.add_parser("update", help="更新浮動損益")

    args = parser.parse_args()

    if args.command in ("long", "short"):
        args.side = args.command
        return open_trade(args)
    elif args.command == "close":
        return close_trade(args.trade_id, exit_price=args.exit)
    elif args.command == "list":
        return list_trades()
    elif args.command == "balance":
        return show_balance()
    elif args.command == "price":
        return show_price(args.symbol)
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
