"""
trade_journal.py — Auto-generated trade journal with lessons learned.
Because professionals journal their trades. Gamblers just check P&L.
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

JOURNAL_PATH = "data/trade_journal.json"


@dataclass
class JournalEntry:
    """A single trade journal entry."""
    # Entry info
    timestamp: str
    symbol: str
    side: str
    entry_price: float
    shares: float
    stop_price: float
    target_price: float
    score: int
    
    # Why we entered
    setup: str  # e.g., "VWAP deviation + volume spike"
    regime: str  # e.g., "trending", "choppy", "volatile"
    
    # Exit info
    exit_price: float = 0.0
    exit_time: str = ""
    exit_reason: str = ""
    pnl: float = 0.0
    pnl_pct: float = 0.0
    
    # Risk management
    initial_risk: float = 0.0
    risk_reward_ratio: float = 0.0
    trailing_stop_used: bool = False
    breakeven_hit: bool = False
    
    # Reflection
    lessons_learned: str = ""
    screenshot_url: str = ""
    emotion: str = ""  # How we felt about the trade
    
    # Status
    status: str = "open"  # open, closed
    
    def to_dict(self) -> dict:
        return asdict(self)


class TradeJournal:
    """Auto-generate and manage trade journal entries."""
    
    def __init__(self):
        self.journal_path = Path(JOURNAL_PATH)
        self.entries: List[Dict] = []
        self._load()
    
    def _load(self):
        """Load journal from file."""
        if self.journal_path.exists():
            with open(self.journal_path, "r") as f:
                self.entries = json.load(f)
        else:
            self.entries = []
    
    def _save(self):
        """Save journal to file."""
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.journal_path, "w") as f:
            json.dump(self.entries, f, indent=2)
    
    def add_entry(self, symbol: str, side: str, entry_price: float, shares: float,
                  stop_price: float, target_price: float, score: int,
                  setup: str, regime: str) -> str:
        """Add a new journal entry when entering a trade."""
        entry_id = f"{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        initial_risk = abs(entry_price - stop_price) * shares
        risk_reward = abs(target_price - entry_price) / abs(entry_price - stop_price) if abs(entry_price - stop_price) > 0 else 0
        
        entry = JournalEntry(
            timestamp=datetime.now().isoformat(),
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            shares=shares,
            stop_price=stop_price,
            target_price=target_price,
            score=score,
            setup=setup,
            regime=regime,
            initial_risk=initial_risk,
            risk_reward_ratio=round(risk_reward, 2),
        )
        
        self.entries.append(entry.to_dict())
        self._save()
        
        logger.info(f"Journal entry added: {entry_id}")
        return entry_id
    
    def close_entry(self, symbol: str, exit_price: float, exit_reason: str,
                    trailing_stop_used: bool = False, breakeven_hit: bool = False,
                    lessons: str = "", emotion: str = ""):
        """Close a journal entry when exiting a trade."""
        for entry in reversed(self.entries):
            if entry['symbol'] == symbol and entry['status'] == 'open':
                entry['exit_price'] = exit_price
                entry['exit_time'] = datetime.now().isoformat()
                entry['exit_reason'] = exit_reason
                entry['trailing_stop_used'] = trailing_stop_used
                entry['breakeven_hit'] = breakeven_hit
                entry['lessons_learned'] = lessons
                entry['emotion'] = emotion
                entry['status'] = 'closed'
                
                # Calculate PnL
                if entry['side'] == 'long':
                    entry['pnl'] = (exit_price - entry['entry_price']) * entry['shares']
                else:
                    entry['pnl'] = (entry['entry_price'] - exit_price) * entry['shares']
                
                entry['pnl_pct'] = (entry['pnl'] / (entry['entry_price'] * entry['shares'])) * 100
                
                self._save()
                
                logger.info(f"Journal entry closed: {symbol} PnL=${entry['pnl']:.2f}")
                return entry
        
        logger.warning(f"No open journal entry found for {symbol}")
        return None
    
    def get_open_trades(self) -> List[Dict]:
        """Get all open journal entries."""
        return [e for e in self.entries if e['status'] == 'open']
    
    def get_closed_trades(self, days: int = 30) -> List[Dict]:
        """Get closed trades from the last N days."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        return [e for e in self.entries if e['status'] == 'closed' and e['exit_time'] >= cutoff]
    
    def get_summary(self) -> Dict:
        """Get journal summary statistics."""
        closed = [e for e in self.entries if e['status'] == 'closed']
        
        if not closed:
            return {"total_trades": 0, "message": "No closed trades yet"}
        
        wins = [e for e in closed if e['pnl'] > 0]
        losses = [e for e in closed if e['pnl'] <= 0]
        
        total_pnl = sum(e['pnl'] for e in closed)
        avg_win = sum(e['pnl'] for e in wins) / len(wins) if wins else 0
        avg_loss = sum(e['pnl'] for e in losses) / len(losses) if losses else 0
        
        # Best setup type
        setups = {}
        for e in closed:
            setup = e.get('setup', 'unknown')
            if setup not in setups:
                setups[setup] = {'count': 0, 'pnl': 0}
            setups[setup]['count'] += 1
            setups[setup]['pnl'] += e['pnl']
        
        best_setup = max(setups, key=lambda x: setups[x]['pnl']) if setups else 'N/A'
        
        # Regime performance
        regimes = {}
        for e in closed:
            regime = e.get('regime', 'unknown')
            if regime not in regimes:
                regimes[regime] = {'count': 0, 'pnl': 0}
            regimes[regime]['count'] += 1
            regimes[regime]['pnl'] += e['pnl']
        
        return {
            "total_trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(closed) * 100, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "best_setup": best_setup,
            "trailing_stop_saved": len([e for e in closed if e.get('trailing_stop_used')]),
            "breakeven_hits": len([e for e in closed if e.get('breakeven_hit')]),
            "regime_performance": regimes,
        }
    
    def get_weekly_summary(self) -> Dict:
        """Get this week's trading summary."""
        now = datetime.now()
        start_of_week = now - timedelta(days=now.weekday())
        start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
        
        week_trades = [e for e in self.entries 
                       if e['status'] == 'closed' and e['exit_time'] >= start_of_week.isoformat()]
        
        if not week_trades:
            return {"message": "No trades this week"}
        
        total_pnl = sum(e['pnl'] for e in week_trades)
        wins = len([e for e in week_trades if e['pnl'] > 0])
        losses = len([e for e in week_trades if e['pnl'] <= 0])
        
        return {
            "week_of": start_of_week.strftime("%Y-%m-%d"),
            "total_trades": len(week_trades),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / len(week_trades) * 100, 1),
            "total_pnl": round(total_pnl, 2),
            "best_trade": max(week_trades, key=lambda x: x['pnl'])['symbol'],
            "worst_trade": min(week_trades, key=lambda x: x['pnl'])['symbol'],
        }
    
    def generate_trade_report(self, entry_id: str) -> str:
        """Generate a human-readable trade report."""
        entry = next((e for e in self.entries if f"{e['symbol']}_{e['timestamp'][:19]}" == entry_id), None)
        if not entry:
            return "Trade not found"
        
        lines = [
            f"═══ TRADE REPORT: {entry['symbol']} ═══",
            f"",
            f"Entry: {entry['side'].upper()} @ ${entry['entry_price']:.2f}",
            f"Size: {entry['shares']} shares",
            f"Stop: ${entry['stop_price']:.2f} ({abs(entry['stop_price'] - entry['entry_price']) / entry['entry_price'] * 100:.2f}%)",
            f"Target: ${entry['target_price']:.2f} ({abs(entry['target_price'] - entry['entry_price']) / entry['entry_price'] * 100:.2f}%)",
            f"Score: {entry['score']}/8",
            f"Setup: {entry.get('setup', 'N/A')}",
            f"Regime: {entry.get('regime', 'N/A')}",
            f"",
        ]
        
        if entry['status'] == 'closed':
            lines.extend([
                f"Exit: ${entry['exit_price']:.2f}",
                f"Reason: {entry.get('exit_reason', 'N/A')}",
                f"P&L: ${entry['pnl']:+.2f} ({entry['pnl_pct']:+.2f}%)",
                f"Trailing Stop: {'Yes' if entry.get('trailing_stop_used') else 'No'}",
                f"Breakeven Hit: {'Yes' if entry.get('breakeven_hit') else 'No'}",
                f"",
                f"Lessons: {entry.get('lessons_learned', 'None recorded')}",
                f"Emotion: {entry.get('emotion', 'N/A')}",
            ])
        else:
            lines.append(f"Status: OPEN")
        
        return "\n".join(lines)


# Global journal instance
journal = TradeJournal()
