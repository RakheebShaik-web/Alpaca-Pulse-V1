"""Independent single-symbol replays, not a combined portfolio backtest."""
from backtest import run_backtest
from config import config


def main():
    for symbol in config.universe:
        run_backtest(symbol, days=7)


if __name__ == '__main__':
    main()
