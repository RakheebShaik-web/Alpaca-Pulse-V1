"""
Discord alert system for trade notifications.
"""
import json
import logging
from datetime import datetime
from typing import Optional

from trade_journal import exit_reason_label

import requests

logger = logging.getLogger(__name__)


class DiscordNotifier:
    """Send trade alerts to Discord via webhook."""
    
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.enabled = bool(webhook_url)
    
    def send(self, content: str, embeds: Optional[list] = None) -> bool:
        """Send a message to Discord."""
        if not self.enabled:
            logger.debug("Discord not configured, skipping")
            return False
        
        payload = {"content": content}
        if embeds:
            payload["embeds"] = embeds
        
        try:
            resp = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Discord send failed: {e}")
            return False
    
    def send_trade_alert(self, trade: dict):
        """Send a formatted trade alert."""
        symbol = trade.get("symbol", "???").upper()
        side = trade.get("side", trade.get("direction", "long")).upper()
        quantity = trade.get("quantity", trade.get("size", 0))
        heading = f"{symbol} {side} {quantity:g}" if isinstance(quantity, (int, float)) else f"{symbol} {side} {quantity}"
        
        embed = {
            "title": heading,
            "color": 0x2F855A if side == "LONG" else 0xC53030,
            "fields": [
                {"name": "Entry", "value": f"${trade.get('entry', 0):.2f}", "inline": True},
                {"name": "Stop Loss", "value": f"${trade.get('stop', 0):.2f}", "inline": True},
                {"name": "Take Profit", "value": f"${trade.get('tp', 0):.2f}", "inline": True},
                {"name": "Quantity", "value": str(quantity), "inline": True},
                {"name": "Risk", "value": f"${trade.get('risk', 0):.2f}", "inline": True},
                {"name": "Gap", "value": f"{trade.get('gap_pct', 0):+.2%}", "inline": True},
            ],
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        self.send(heading, embeds=[embed])
    
    def send_exit_alert(self, trade: dict):
        """Send a trade exit notification."""
        pnl = trade.get("pnl", 0)
        color = 0x00FF00 if pnl > 0 else 0xFF0000
        symbol = trade.get("symbol", "???").upper()
        side = trade.get("side", trade.get("direction", "long")).upper()
        quantity = trade.get("quantity", trade.get("size", 0))
        quantity_text = f"{quantity:g}" if isinstance(quantity, (int, float)) else str(quantity)
        reason = exit_reason_label(trade.get("exit_reason", ""))
        heading = f"{symbol} {side} {quantity_text} | EXIT {reason}"
        
        embed = {
            "title": heading,
            "color": color,
            "fields": [
                {"name": "Reason", "value": reason, "inline": True},
                {"name": "Entry", "value": f"${trade.get('entry', 0):.2f}", "inline": True},
                {"name": "Exit", "value": f"${trade.get('exit_price', 0):.2f}", "inline": True},
                {"name": "PnL", "value": f"${pnl:+.2f}", "inline": True},
                {"name": "Daily PnL", "value": f"${trade.get('daily_pnl', 0):+.2f}", "inline": True},
            ],
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        self.send(heading, embeds=[embed])
    
    def send_daily_summary(self, summary: dict):
        """Send end-of-day summary."""
        pnl = summary.get("daily_pnl", 0)
        emoji = "📈" if pnl > 0 else "📉"
        color = 0x00FF00 if pnl > 0 else 0xFF0000
        
        embed = {
            "title": f"{emoji} Daily Summary — {summary.get('date', 'Today')}",
            "color": color,
            "fields": [
                {"name": "Trades", "value": str(summary.get("trades", 0)), "inline": True},
                {"name": "Win Rate", "value": f"{summary.get('win_rate', 0):.0%}", "inline": True},
                {"name": "Daily PnL", "value": f"${pnl:+.2f}", "inline": True},
                {"name": "Portfolio", "value": f"${summary.get('portfolio', 0):,.2f}", "inline": True},
            ],
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        self.send("**Daily Trading Summary**", embeds=[embed])
    
    def send_scan_results(self, setups: list):
        """Send pre-market scan results."""
        if not setups:
            return
        
        lines = []
        for s in setups[:10]:  # Top 10
            direction = "🟢 LONG" if s["direction"] == "long" else "🔴 SHORT"
            lines.append(
                f"**{s['symbol']}** | {direction} | Gap: {s['gap_pct']:+.2%} | "
                f"Vol: {s['pm_volume']:,}"
            )
        
        embed = {
            "title": f"🔍 Pre-Market Scan — {len(setups)} setup(s)",
            "description": "\n".join(lines),
            "color": 0x3498DB,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        self.send("**Pre-Market Scan Results**", embeds=[embed])
