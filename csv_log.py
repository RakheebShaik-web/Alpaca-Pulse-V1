"""
csv_log.py — Institutional trade logging.
Logs all trades to CSV with full audit trail.
"""
import csv
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CSV_PATH = os.environ.get("TRADES_CSV_PATH", "data/trades.csv")

# CSV columns
COLUMNS = [
    "timestamp",
    "symbol",
    "side",
    "entry_price",
    "exit_price",
    "shares",
    "stop_price",
    "target_price",
    "pnl",
    "pnl_pct",
    "exit_reason",
    "status",
    "notes",
]


def ensure_csv_exists():
    """Create CSV with headers if it doesn't exist."""
    csv_path = Path(CSV_PATH)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    
    if not csv_path.exists():
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()
        logger.info(f"Created trades CSV at {csv_path}")


def log_trade(
    symbol: str,
    side: str,
    entry_price: float,
    exit_price: float = 0.0,
    shares: float = 0.0,
    stop_price: float = 0.0,
    target_price: float = 0.0,
    pnl: float = 0.0,
    pnl_pct: float = 0.0,
    exit_reason: str = "",
    status: str = "open",
    notes: str = "",
):
    """Log a trade to CSV."""
    try:
        ensure_csv_exists()
        
        with open(CSV_PATH, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writerow({
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "side": side,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "shares": shares,
                "stop_price": stop_price,
                "target_price": target_price,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "exit_reason": exit_reason,
                "status": status,
                "notes": notes,
            })
        
        logger.info(f"Trade logged: {symbol} {side} @ ${entry_price:.2f}")
    except Exception as e:
        logger.error(f"Failed to log trade: {e}")


def update_trade(position_id: str, exit_price: float, pnl: float, exit_reason: str):
    """Update a trade record with exit data."""
    try:
        csv_path = Path(CSV_PATH)
        if not csv_path.exists():
            return
        
        # Read all rows
        rows = []
        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("notes", "").find(position_id) != -1:
                    row["exit_price"] = exit_price
                    row["pnl"] = pnl
                    row["exit_reason"] = exit_reason
                    row["status"] = "closed"
                rows.append(row)
        
        # Write back
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        
        logger.info(f"Trade updated: {position_id} PnL=${pnl:.2f}")
    except Exception as e:
        logger.error(f"Failed to update trade: {e}")


def get_open_trades() -> list:
    """Get all open trades from CSV."""
    try:
        csv_path = Path(CSV_PATH)
        if not csv_path.exists():
            return []
        
        open_trades = []
        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("status") == "open":
                    open_trades.append(row)
        
        return open_trades
    except Exception as e:
        logger.error(f"Failed to get open trades: {e}")
        return []


def get_trade_summary() -> dict:
    """Get summary statistics — pulls realized PnL from Alpaca."""
    try:
        from main import system
        if not system.trader:
            return {"total_trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0}
        
        account = system.trader.get_account()
        if account:
            equity = float(account.get('equity', 0))
            last_equity = float(account.get('last_equity', equity))
            realized_pnl = equity - last_equity
            
            # Count trades from Alpaca history
            orders = system.trader.get_orders(status="closed")
            filled_orders = [o for o in orders if o.get('filled_qty', 0) > 0]
            
            # Rough estimate: each pair of fills = 1 round-trip trade
            total_trades = len(filled_orders) // 2 if filled_orders else 0
            
            return {
                "total_trades": total_trades,
                "wins": 0,  # Would need per-trade calculation from Alpaca
                "losses": 0,
                "total_pnl": round(realized_pnl, 2),
                "equity": round(equity, 2),
                "last_equity": round(last_equity, 2),
            }
    except Exception as e:
        logger.error(f"Failed to get Alpaca summary: {e}")
    
    return {"total_trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0}
