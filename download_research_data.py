"""Private local key prompt and read-only QQQ historical-data download."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
import tkinter as tk
from tkinter import ttk


def main():
    root = tk.Tk()
    root.title('Pulse — Historical data setup')
    root.geometry('540x310')
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Download QQQ history', font=('Segoe UI', 16)).pack(anchor='w')
    ttk.Label(frame, text='Keys stay in memory. No orders are placed.').pack(anchor='w', pady=(8, 16))
    fields = []
    for label in ('ALPACA_API_KEY', 'ALPACA_SECRET_KEY'):
        ttk.Label(frame, text=label).pack(anchor='w')
        entry = ttk.Entry(frame, show='*', width=65)
        entry.pack(fill='x', pady=(3, 10))
        fields.append(entry)
    status = tk.StringVar(value='Uses the IEX feed; coverage differs from the full US market.')

    def start():
        key, secret = [entry.get().strip() for entry in fields]
        if not key or not secret:
            status.set('Paste both keys from Render to continue.')
            return
        for entry in fields:
            entry.delete(0, 'end')
        button.configure(state='disabled')
        status.set('Downloading six months of minute bars. Please leave this window open.')

        def work():
            try:
                from alpaca.data.historical import StockHistoricalDataClient
                from alpaca.data.requests import StockBarsRequest
                from alpaca.data.timeframe import TimeFrame
                from alpaca.data.enums import DataFeed, Adjustment
                client = StockHistoricalDataClient(key, secret)
                end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                request = StockBarsRequest(symbol_or_symbols=['QQQ'], timeframe=TimeFrame.Minute,
                                           start=end - timedelta(days=183), end=end,
                                           feed=DataFeed.IEX, adjustment=Adjustment.SPLIT)
                bars = client.get_stock_bars(request).df
                bars = bars.xs('QQQ', level='symbol')
                bars.index = bars.index.tz_convert('America/New_York')
                bars = bars.between_time('09:30', '16:00', inclusive='left')
                if bars.empty:
                    raise ValueError('empty data')
                folder = Path(__file__).resolve().parent / 'data' / 'research'
                folder.mkdir(parents=True, exist_ok=True)
                bars[['open', 'high', 'low', 'close', 'volume']].to_csv(folder / 'QQQ_1min.csv')
                root.after(0, status.set, f'Done: {len(bars):,} bars saved. Tell Codex “download done”.')
            except Exception:
                # Never display request headers, credentials, or raw API errors.
                root.after(0, status.set, 'Download failed. Check the keys and connection, then retry.')
            finally:
                root.after(0, lambda: button.configure(state='normal'))
        threading.Thread(target=work, daemon=True).start()

    button = ttk.Button(frame, text='Download history', command=start)
    button.pack(anchor='w', pady=8)
    ttk.Label(frame, textvariable=status, wraplength=490).pack(anchor='w')
    root.mainloop()


if __name__ == '__main__':
    main()
