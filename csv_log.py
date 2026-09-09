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
    """Get summary statistics from trade log."""
    try:
        csv_path = Path(CSV_PATH)
        if not csv_path.exists():
            return {"total_trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0}
        
        total_trades = 0
        wins = 0
        losses = 0
        total_pnl = 0.0
        
        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("status") == "closed":
                    total_trades += 1
                    pnl = float(row.get("pnl", 0))
                    total_pnl += pnl
                    if pnl > 0:
                        wins += 1
                    else:
                        losses += 1
        
        return {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "total_pnl": total_pnl,
            "win_rate": (wins / total_trades * 100) if total_trades > 0 else 0,
        }
    except Exception as e:
        logger.error(f"Failed to get trade summary: {e}")
        return {"total_trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0}
