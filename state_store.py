"""
state_store.py — Crash-safe persistence for bot state.

On startup, load_state() recovers positions after crash/restart.
On every state change, save_state() writes atomically to JSON.
"""

import json
import logging
import os
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, Dict, List
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_PATH = os.environ.get("BOT_STATE_PATH", "data/bot_state.json")
STATE_SCHEMA_VERSION = 1


@dataclass
class TradePosition:
    position_id: str
    symbol: str
    side: str  # "long" or "short"
    entry_price: float
    shares: float
    shares_remaining: float
    stop_price: float
    target_price: float
    tp1_filled: bool = False
    tp2_filled: bool = False
    tp3_filled: bool = False
    opened_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    notes: str = ""


@dataclass
class BotState:
    version: int = STATE_SCHEMA_VERSION
    balance: float = 20000.0
    daily_pnl: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    last_trade_at: Optional[str] = None
    last_sl_at: Optional[str] = None
    positions: Dict[str, List[Position]] = field(default_factory=dict)
    
    def all_positions(self) -> List[Position]:
        all_pos = []
        for symbol, positions in self.positions.items():
            all_pos.extend(positions)
        return all_pos
    
    def get_position(self, position_id: str) -> Optional[Position]:
        for symbol, positions in self.positions.items():
            for pos in positions:
                if pos.position_id == position_id:
                    return pos
        return None
    
    def add_position(self, position: Position):
        if position.symbol not in self.positions:
            self.positions[position.symbol] = []
        self.positions[position.symbol].append(position)
    
    def remove_position(self, position_id: str):
        for symbol, positions in self.positions.items():
            self.positions[symbol] = [p for p in positions if p.position_id != position_id]
            if not self.positions[symbol]:
                del self.positions[symbol]
    
    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "balance": self.balance,
            "daily_pnl": self.daily_pnl,
            "trades_today": self.trades_today,
            "consecutive_losses": self.consecutive_losses,
            "last_trade_at": self.last_trade_at,
            "last_sl_at": self.last_sl_at,
            "positions": {
                symbol: [asdict(p) for p in positions]
                for symbol, positions in self.positions.items()
            }
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "BotState":
        state = cls()
        state.version = data.get("version", STATE_SCHEMA_VERSION)
        state.balance = data.get("balance", 20000.0)
        state.daily_pnl = data.get("daily_pnl", 0.0)
        state.trades_today = data.get("trades_today", 0)
        state.consecutive_losses = data.get("consecutive_losses", 0)
        state.last_trade_at = data.get("last_trade_at")
        state.last_sl_at = data.get("last_sl_at")
        
        for symbol, positions in data.get("positions", {}).items():
            state.positions[symbol] = []
            for p in data["positions"][symbol]:
                state.positions[symbol].append(Position(**p))
        
        return state


def load_state() -> BotState:
    """Load state from JSON file. Returns fresh state if file doesn't exist."""
    state_path = Path(STATE_PATH)
    
    if not state_path.exists():
        logger.info("No state file found, starting fresh")
        return BotState()
    
    try:
        with open(state_path, "r") as f:
            data = json.load(f)
        
        state = BotState.from_dict(data)
        logger.info(f"Loaded state: {len(state.all_positions())} open position(s), balance ${state.balance:.2f}")
        return state
    except Exception as e:
        logger.error(f"Failed to load state: {e}")
        # Try backup
        bak_path = state_path.with_suffix(".bak")
        if bak_path.exists():
            try:
                with open(bak_path, "r") as f:
                    data = json.load(f)
                state = BotState.from_dict(data)
                logger.warning("Loaded state from backup file")
                return state
            except Exception:
                pass
        return BotState()


def save_state(state: BotState):
    """Save state atomically to JSON file."""
    state_path = Path(STATE_PATH)
    
    # Ensure directory exists
    state_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Backup existing state
    if state_path.exists():
        bak_path = state_path.with_suffix(".bak")
        shutil.copy2(state_path, bak_path)
    
    # Write to temp file then atomically replace
    tmp_path = state_path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w") as f:
            json.dump(state.to_dict(), f, indent=2)
        
        # Atomic replace
        os.replace(tmp_path, state_path)
        logger.debug(f"State saved: {len(state.all_positions())} positions")
    except Exception as e:
        logger.error(f"Failed to save state: {e}")
        if tmp_path.exists():
            tmp_path.unlink()


def new_position(
    symbol: str,
    side: str,
    entry_price: float,
    shares: float,
    stop_price: float,
    target_price: float,
) -> TradePosition:
    """Create a new position with a unique ID."""
    import uuid
    return TradePosition(
        position_id=str(uuid.uuid4())[:8],
        symbol=symbol,
        side=side,
        entry_price=entry_price,
        shares=shares,
        shares_remaining=shares,
        stop_price=stop_price,
        target_price=target_price,
    )
