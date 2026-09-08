#!/usr/bin/env python3
"""
Run 6-month backtests on all 10 symbols and generate a summary report.
"""

import sys
import logging
from datetime import datetime

from config import config
from backtest import run_backtest, fetch_yahoo_data

logging.basicConfig(level=logging.WARNING, format='%(asctime)s | %(message)s')

def main():
    symbols = list(config.universe)
    days = 180  # 6 months
    
    print(f"\n{'=' * 70}")
    print(f"6-MONTH BACKTEST SUITE | {days} days | ${config.capital:,.0f} capital")
    print(f"Risk: ${config.risk_per_trade}/trade | Max Loss: ${config.max_daily_loss}/day")
    print(f"RR: {config.rr_ratio}:1 | Gap Threshold: {config.gap_threshold:.1%}")
    print(f"{'=' * 70}\n")
    
    results = []
    
    for i, symbol in enumerate(symbols, 1):
        print(f"\n[{i}/{len(symbols)}] Running {symbol}...")
        try:
            report = run_backtest(symbol, days, discord_webhook=None)
            if report:
                results.append(report)
                print(f"  ✓ {symbol}: {report.get('total_return', 0):+.2f}% | "
                      f"WR: {report.get('win_rate', 0):.0%} | "
                      f"Trades: {report.get('total_trades', 0)} | "
                      f"PF: {report.get('profit_factor', 0):.2f}")
        except Exception as e:
            print(f"  ✗ {symbol}: ERROR - {e}")
    
    # Summary table
    print(f"\n\n{'=' * 70}")
    print("SUMMARY RESULTS (Sorted by Profit Factor)")
    print(f"{'=' * 70}")
    print(f"{'Symbol':<8} {'Return':>8} {'Win Rate':>10} {'Trades':>8} {'PF':>8} {'Max DD':>8}")
    print(f"{'-' * 50}")
    
    # Sort by profit factor
    results.sort(key=lambda x: x.get('profit_factor', 0), reverse=True)
    
    for r in results:
        print(f"{r['symbol']:<8} {r.get('total_return', 0):>+7.2f}% "
              f"{r.get('win_rate', 0):>9.0%} "
              f"{r.get('total_trades', 0):>8} "
              f"{r.get('profit_factor', 0):>8.2f} "
              f"{r.get('max_drawdown', 0):>7.2f}%")
    
    # Best performer
    if results:
        best = results[0]
        print(f"\n🏆 BEST: {best['symbol']} | "
              f"Return: {best.get('total_return', 0):+.2f}% | "
              f"PF: {best.get('profit_factor', 0):.2f}")
    
    print(f"\n{'=' * 70}")


if __name__ == '__main__':
    main()
