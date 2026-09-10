"""
earnings_filter.py — Skip stocks with earnings today.
Earnings = unpredictable volatility = bad for mean reversion.
"""
import logging
from datetime import datetime
from typing import Dict, Set
from pathlib import Path
import json

logger = logging.getLogger(__name__)

EARNINGS_CACHE_PATH = "data/earnings_cache.json"


class EarningsFilter:
    """Track and filter stocks with upcoming earnings."""
    
    def __init__(self):
        self.cache_path = Path(EARNINGS_CACHE_PATH)
        self.earnings_calendar: Dict[str, str] = {}
        self._load_cache()
    
    def _load_cache(self):
        """Load earnings calendar from cache."""
        if self.cache_path.exists():
            with open(self.cache_path, "r") as f:
                self.earnings_calendar = json.load(f)
    
    def _save_cache(self):
        """Save earnings calendar to cache."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "w") as f:
            json.dump(self.earnings_calendar, f, indent=2)
    
    def is_earnings_day(self, symbol: str) -> bool:
        """Check if a stock has earnings today."""
        today = datetime.now().strftime("%Y-%m-%d")
        return self.earnings_calendar.get(symbol) == today
    
    def get_earnings_today(self) -> Set[str]:
        """Get all stocks with earnings today."""
        today = datetime.now().strftime("%Y-%m-%d")
        return {sym for sym, date in self.earnings_calendar.items() if date == today}
    
    def update_calendar(self, symbol: str, earnings_date: str):
        """Update earnings calendar with new data."""
        self.earnings_calendar[symbol] = earnings_date
        self._save_cache()
    
    def should_skip(self, symbol: str) -> bool:
        """Check if we should skip this symbol due to earnings."""
        if self.is_earnings_day(symbol):
            logger.info(f"Skipping {symbol} - earnings today")
            return True
        return False


# Global earnings filter instance
earnings_filter = EarningsFilter()
