"""Public GET-only market feed; never loads credentials or a broker factory."""
from datetime import datetime
import time
import requests

from .arena import INTERVALS


class PublicFeed:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'TradingLab-PaperArena/1.0'
        self.cache = {}

    def get(self, url, params=None):
        response = self.session.get(url, params=params, timeout=20)
        response.raise_for_status()
        return response.json()

    def candles(self, interval, current):
        boundary = current // INTERVALS[interval]
        if interval not in self.cache or self.cache[interval][0] != boundary:
            raw = self.get('https://api.kraken.com/0/public/OHLC',
                           {'pair': 'XBTUSD', 'interval': INTERVALS[interval] // 60_000})
            if raw.get('error'):
                raise ValueError('Kraken rechazó las velas públicas')
            items = next(value for key, value in raw['result'].items() if key != 'last')
            rows = [[int(r[0]) * 1000, *map(float, r[1:5]), float(r[6])] for r in items
                    if int(r[0]) * 1000 + INTERVALS[interval] <= current]
            if not rows:
                raise ValueError('No hay cierres completos')
            self.cache[interval] = boundary, rows
        return self.cache[interval][1]

    def capture(self):
        start = int(time.time() * 1000)
        candles = {interval: self.candles(interval, start) for interval in INTERVALS}
        raw_trades = self.get('https://bitso.com/api/v3/trades/', {'book': 'btc_usd', 'limit': 100, 'sort': 'desc'})
        raw_book = self.get('https://bitso.com/api/v3/order_book/', {'book': 'btc_usd', 'aggregate': 'true'})
        if not raw_trades.get('success') or not raw_book.get('success'):
            raise ValueError('Bitso no devolvió libro y trades públicos')
        book = raw_book['payload']
        parsed_book = {'updated_ms': int(datetime.fromisoformat(book['updated_at'].replace('Z', '+00:00')).timestamp() * 1000),
                       'sequence': book['sequence']}
        for side in ('bids', 'asks'):
            parsed_book[side] = [[float(x['price']), float(x['amount'])] for x in book[side]]
        trades = [{'tid': int(t['tid']), 'ts': int(datetime.fromisoformat(t['created_at'].replace('Z', '+00:00')).timestamp()*1000),
                   'price': float(t['price']), 'qty': float(t['amount']), 'side': t['maker_side']} for t in raw_trades['payload']]
        return {'kind': 'paper', 'book': 'btc_usd', 'observed_ms': int(time.time() * 1000),
                'order_book': parsed_book, 'trades': trades, 'candles': candles,
                'sources': {'execution': 'Bitso public REST order_book/trades', 'signals': 'Kraken public OHLC BTC/USD'},
                'trades_page_limit': 100}
