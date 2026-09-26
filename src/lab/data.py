"""Datos de precios.

- Investigación: histórico diario de CoinMetrics (gratis, desde 2010) extendido
  con velas recientes de un exchange público (Kraken) para llegar a hoy.
- Bot: velas diarias CERRADAS directamente del exchange vía ccxt.

Convención de fechas: la fila con fecha D es el precio de cierre del día D (UTC).
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
COINMETRICS_URL = "https://raw.githubusercontent.com/coinmetrics/data/master/csv/{asset}.csv"
EXTENSION_SOURCE = {"btc": ("kraken", "BTC/USD"), "eth": ("kraken", "ETH/USD")}
DAY_MS = 86_400_000


def make_exchange(name: str, api_key: str | None = None, secret: str | None = None,
                  password: str | None = None):
    """Crea un cliente ccxt. `requests_trust_env` respeta proxies del sistema."""
    import ccxt

    params = {"enableRateLimit": True, "requests_trust_env": True}
    if api_key:
        params.update(apiKey=api_key, secret=secret)
        if password:
            params["password"] = password
    return getattr(ccxt, name)(params)


def fetch_daily_closes(exchange, symbol: str, days: int = 1000,
                       now_ms: int | None = None) -> pd.Series:
    """Cierres diarios de velas COMPLETAS (descarta la vela del día en curso).

    Usar la vela en curso sería usar un precio que todavía no existe al cierre:
    es el error de "mirar al futuro" más común en bots caseros.
    """
    ohlcv = exchange.fetch_ohlcv(symbol, "1d", limit=days)
    if not ohlcv:
        raise RuntimeError(f"{exchange.id} no devolvió velas para {symbol}")
    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
    now_ms = exchange.milliseconds() if now_ms is None else now_ms
    df = df[df["ts"] + DAY_MS <= now_ms]
    idx = pd.to_datetime(df["ts"], unit="ms").dt.normalize()
    s = pd.Series(df["close"].astype(float).values, index=pd.DatetimeIndex(idx), name="close")
    return s[~s.index.duplicated(keep="last")].sort_index()


def download_coinmetrics(asset: str = "btc") -> pd.Series:
    import requests

    r = requests.get(COINMETRICS_URL.format(asset=asset), timeout=90)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), usecols=["time", "PriceUSD"], parse_dates=["time"])
    s = df.dropna().set_index("time")["PriceUSD"].astype(float)
    s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
    s.name = "close"
    return s[s > 0]


def load_history(asset: str = "btc", refresh: bool = False, extend: bool = True) -> pd.Series:
    """Serie diaria de cierres en USD. Se guarda en data/ para no descargar cada vez."""
    path = DATA_DIR / f"{asset}_usd_daily.csv"
    if path.exists() and not refresh:
        s = pd.read_csv(path, index_col=0, parse_dates=True)["close"]
        s.index = pd.DatetimeIndex(s.index)
        return s.astype(float)

    s = download_coinmetrics(asset)
    if extend and asset in EXTENSION_SOURCE:
        ex_name, symbol = EXTENSION_SOURCE[asset]
        try:
            live = fetch_daily_closes(make_exchange(ex_name), symbol, days=720)
            s = pd.concat([s, live[live.index > s.index[-1]]])
        except Exception as exc:  # sin red: nos quedamos con CoinMetrics
            print(f"[aviso] no pude extender con {ex_name} {symbol}: {exc}")
    DATA_DIR.mkdir(exist_ok=True)
    s.to_frame("close").to_csv(path)
    return s


# ============================================================ multi-activo
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}


def yahoo_daily(symbol: str, start: str = "1995-01-01", retries: int = 6) -> pd.Series:
    """Cierres diarios ajustados (dividendos y splits) de Yahoo Finance. Sin llave de API."""
    import time

    import requests

    p1 = int(pd.Timestamp(start).timestamp())
    p2 = int(time.time()) + 86_400
    params = {"period1": p1, "period2": p2, "interval": "1d", "includeAdjustedClose": "true",
              "events": "div,split"}
    for k in range(retries):
        r = requests.get(YAHOO_URL.format(symbol=symbol), params=params, headers=YAHOO_HEADERS, timeout=30)
        if r.status_code == 429:
            time.sleep(2 ** k)
            continue
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        ts = res.get("timestamp") or []
        ind = res["indicators"]
        close = list((ind.get("adjclose") or [{}])[0].get("adjclose") or ind["quote"][0]["close"])
        meta = res.get("meta") or {}
        reg = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
        if (ts and close and close[-1] is None and meta.get("regularMarketPrice") and reg.get("end")
                and meta.get("regularMarketTime", 0) >= reg["end"] and ts[-1] >= reg.get("start", 0)):
            # Yahoo tarda horas en llenar la barra diaria aunque la sesión ya cerró:
            # se usa el precio de cierre oficial de la sesión.
            close[-1] = float(meta["regularMarketPrice"])
        idx = pd.to_datetime(pd.Series(ts), unit="s").dt.normalize()
        s = pd.Series(close, index=pd.DatetimeIndex(idx), dtype=float, name=symbol).dropna()
        return s[~s.index.duplicated(keep="last")]
    raise RuntimeError(f"Yahoo limitó las solicitudes para {symbol}")


def yahoo_last(symbol: str) -> tuple[float, pd.Timestamp]:
    """Último precio de Yahoo (en sesión: el del momento; fuera de sesión: el cierre) y su hora UTC."""
    import requests

    r = requests.get(YAHOO_URL.format(symbol=symbol), params={"range": "1d", "interval": "1d"},
                     headers=YAHOO_HEADERS, timeout=20)
    r.raise_for_status()
    meta = r.json()["chart"]["result"][0]["meta"]
    return float(meta["regularMarketPrice"]), pd.Timestamp(meta["regularMarketTime"], unit="s")


# Criptos que alguna vez fueron grandes, INCLUYENDO las que se desplomaron o murieron
# (LUNA, FTT, EOS, NEO, IOTA...). Elegir solo las que hoy siguen vivas inflaría el backtest.
CRYPTO_RESEARCH = {
    # símbolo: (id en CoinMetrics o None, ticker de Yahoo)
    "BTC": ("btc", "BTC-USD"), "ETH": ("eth", "ETH-USD"), "XRP": ("xrp", "XRP-USD"),
    "LTC": ("ltc", "LTC-USD"), "BCH": ("bch", "BCH-USD"), "ADA": ("ada", "ADA-USD"),
    "DOGE": ("doge", "DOGE-USD"), "SOL": ("sol", "SOL-USD"), "DOT": ("dot", "DOT-USD"),
    "LINK": ("link", "LINK-USD"), "AVAX": ("avax", "AVAX-USD"), "TRX": ("trx", "TRX-USD"),
    "XLM": ("xlm", "XLM-USD"), "BNB": ("bnb", "BNB-USD"), "MATIC": ("matic", "POL28321-USD|MATIC-USD"),
    "ATOM": ("atom", "ATOM-USD"), "UNI": ("uni", "UNI7083-USD"), "ETC": ("etc", "ETC-USD"),
    "XMR": ("xmr", "XMR-USD"), "EOS": ("eos", "EOS-USD"), "NEO": ("neo", "NEO-USD"),
    "XEM": ("xem", "XEM-USD"), "DASH": ("dash", "DASH-USD"), "IOTA": ("miota", "IOTA-USD"),
    "ZEC": ("zec", "ZEC-USD"), "XTZ": ("xtz", "XTZ-USD"), "VET": ("vet", "VET-USD"),
    "LUNA": ("luna", "LUNC-USD"), "FTT": ("ftt", "FTT-USD"), "ALGO": ("algo", "ALGO-USD"),
    "FIL": ("fil", "FIL-USD"), "ICP": ("icp", "ICP-USD"), "SHIB": ("shib", "SHIB-USD"),
    "NEAR": ("near", "NEAR-USD"), "HBAR": ("hbar", "HBAR-USD"), "BSV": ("bsv", "BSV-USD"),
    "WAVES": ("waves", "WAVES-USD"), "OMG": ("omg", "OMG-USD"), "QTUM": ("qtum", "QTUM-USD"),
}
STABLECOINS = {"USDT", "USDC", "DAI", "BUSD", "UST", "TUSD", "PYUSD", "RLUSD"}

ETF_RESEARCH = ["SPY", "QQQ", "IWM", "EFA", "EEM", "EWW", "TLT", "IEF", "GLD", "DBC", "VNQ",
                "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLU", "XLY", "XLB"]


def _coinmetrics_frame(asset: str) -> pd.DataFrame:
    import requests

    r = requests.get(COINMETRICS_URL.format(asset=asset), timeout=120)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), low_memory=False, parse_dates=["time"])
    df = df.set_index("time")
    df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    out = pd.DataFrame(index=df.index)
    out["price"] = df["PriceUSD"] if "PriceUSD" in df else float("nan")
    cur = df["CapMrktCurUSD"] if "CapMrktCurUSD" in df else pd.Series(float("nan"), index=df.index)
    est = df["CapMrktEstUSD"] if "CapMrktEstUSD" in df else pd.Series(float("nan"), index=df.index)
    out["mcap"] = cur.fillna(est)
    return out


def load_crypto_panel(refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(precios, capitalización) diarios en USD. Precio: CoinMetrics, completado con Yahoo."""
    import concurrent.futures as cf
    import time

    pp, mp = DATA_DIR / "crypto_prices.csv", DATA_DIR / "crypto_mcap.csv"
    if pp.exists() and mp.exists() and not refresh:
        read = lambda p: pd.read_csv(p, index_col=0, parse_dates=True)  # noqa: E731
        return read(pp), read(mp)

    with cf.ThreadPoolExecutor(8) as ex:
        cm = dict(zip(CRYPTO_RESEARCH, ex.map(lambda a: _coinmetrics_frame(a[0]),
                                                CRYPTO_RESEARCH.values())))
    prices, mcaps = {}, {}
    for sym, (cm_id, ysym) in CRYPTO_RESEARCH.items():
        f = cm[sym]
        y = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
        for tk in ysym.split("|"):  # tickers alternativos separados por |
            try:
                y = yahoo_daily(tk, start="2014-01-01")
                time.sleep(0.5)
                break
            except Exception as exc:
                print(f"[aviso] Yahoo {tk}: {exc}")
        p = f["price"].dropna()
        if not len(p) and not len(y):
            continue
        # Yahoo llena donde CoinMetrics no tiene precio (y después de su última fecha)
        p = p.combine_first(y) if len(p) else y
        m = f["mcap"].dropna()
        if len(m) and len(p) and m.index[0] < p.index[0] and p.index[0] in m.index:
            # Sin precio al inicio (p. ej. IOTA, MATIC antes de 2023): se aproxima con la
            # capitalización escalada. Exacto si la oferta es fija; aproximado si no.
            proxy = m[m.index < p.index[0]] * (p.iloc[0] / m.loc[p.index[0]])
            p = pd.concat([proxy, p])
        if len(m):  # después del último dato de capitalización, la escalamos con el precio
            tail = p[p.index > m.index[-1]]
            if len(tail) and m.index[-1] in p.index:
                m = pd.concat([m, m.iloc[-1] * tail / p.loc[m.index[-1]]])
        prices[sym], mcaps[sym] = p, m
    P = pd.DataFrame(prices).sort_index()
    M = pd.DataFrame(mcaps).reindex(P.index)
    last_full = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)
    P = P.loc["2014-01-01":last_full]   # la vela de hoy aún no cierra
    M = M.loc["2014-01-01":last_full]
    DATA_DIR.mkdir(exist_ok=True)
    P.to_csv(pp)
    M.to_csv(mp)
    return P, M


MULTI_MARKET = ["GLD", "SLV", "DBC", "USO", "DBA", "DBB",   # materias primas
                "UUP", "FXE", "FXY",                        # divisas
                "TLT", "IEF", "TIP", "LQD",                 # bonos
                "SPY", "EFA", "EEM", "EWW", "EWJ", "VNQ",   # bolsas y bienes raíces
                "BIL"]                                      # efectivo: letras del Tesoro de 1-3 meses


def load_etf_panel(symbols: list[str] | None = None, refresh: bool = False,
                   name: str = "etf_prices") -> pd.DataFrame:
    import time

    path = DATA_DIR / f"{name}.csv"
    if path.exists() and not refresh:
        return pd.read_csv(path, index_col=0, parse_dates=True)
    out = {}
    for s in symbols or ETF_RESEARCH:
        out[s] = yahoo_daily(s, start="1998-01-01")
        time.sleep(0.5)
    P = pd.DataFrame(out).sort_index()
    now_ny = pd.Timestamp.now(tz="America/New_York")
    if now_ny.hour < 17:  # antes del cierre, la fila de hoy es parcial
        P = P.loc[: now_ny.normalize().tz_localize(None) - pd.Timedelta(days=1)]
    DATA_DIR.mkdir(exist_ok=True)
    P.to_csv(path)
    return P


# ============================================================ velas por hora (tiempo real)
HOUR_MS = 3_600_000
# (exchange, velas por solicitud). Se usa, por cripto, la fuente con historia más antigua.
HOURLY_SOURCES = [("bitstamp", 1000), ("coinbaseexchange", 300)]


def fetch_hourly(exchange, symbol: str, since_ms: int, limit: int, now_ms: int | None = None) -> pd.Series:
    """Cierres por hora de velas COMPLETAS, indexados por la hora en que CIERRA la vela (UTC).

    La vela de las 23:00 cierra a las 00:00: ese precio es el cierre diario que usa el bot.
    """
    now_ms = exchange.milliseconds() if now_ms is None else now_ms
    rows, since = [], since_ms
    while since < now_ms:
        batch = _retry(lambda: exchange.fetch_ohlcv(symbol, "1h", since=since, limit=limit))
        batch = [b for b in batch if b[0] >= since]
        if not batch:
            since += limit * HOUR_MS  # hueco (o antes de que existiera el par): avanzar
            continue
        rows += batch
        since = batch[-1][0] + HOUR_MS
    rows = [r for r in rows if r[0] + HOUR_MS <= now_ms]  # la vela en curso todavía no existe
    if not rows:
        return pd.Series(dtype=float)
    ts = pd.to_datetime([r[0] + HOUR_MS for r in rows], unit="ms")
    s = pd.Series([float(r[4]) for r in rows], index=pd.DatetimeIndex(ts), name=symbol)
    return s[~s.index.duplicated(keep="last")].sort_index()


def _retry(fn, tries: int = 8):
    """Reintenta con espera creciente si el exchange limita las solicitudes o falla la red."""
    import time

    import ccxt

    for k in range(tries):
        try:
            return fn()
        except (ccxt.RateLimitExceeded, ccxt.NetworkError):
            if k == tries - 1:
                raise
            time.sleep(min(60, 2 ** k))


def _first_day(exchange, symbol: str, start_ms: int, now_ms: int) -> int | None:
    """Primer día con velas del par (sondea con velas diarias en ventanas de 300 días)."""
    since = start_ms
    while since < now_ms:
        o = _retry(lambda: exchange.fetch_ohlcv(symbol, "1d", since=since, limit=300))
        o = [b for b in o if b[0] >= since]
        if o:
            return int(o[0][0])
        since += 300 * DAY_MS
    return None


def load_hourly_panel(coins: list[str], refresh: bool = False, start: str = "2020-01-01",
                      quote: str = "USD") -> pd.DataFrame:
    """Panel de cierres por hora (índice = hora de cierre de la vela, UTC). Caché en data/.

    Con refresh solo descarga lo nuevo desde la última hora guardada.
    """
    import concurrent.futures as cf

    path = DATA_DIR / "hourly_prices.csv"
    old = pd.read_csv(path, index_col=0, parse_dates=True) if path.exists() else pd.DataFrame()
    if len(old) and not refresh and set(coins) <= set(old.columns):
        return old[coins]
    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)

    def one(coin: str) -> tuple[str, pd.Series, str]:
        best = None
        for name, limit in HOURLY_SOURCES:
            ex = make_exchange(name)
            ex.load_markets()
            sym = f"{coin}/{quote}"
            if sym not in ex.markets:
                continue
            now_ms = ex.milliseconds()
            if coin in old.columns and old[coin].notna().any():
                first = start_ms  # ya se conoce la fuente; solo falta lo nuevo
            else:
                first = _first_day(ex, sym, start_ms, now_ms)
            if first is not None and (best is None or first < best[2]):
                best = (ex, sym, first, limit)
        if best is None:
            return coin, pd.Series(dtype=float), "sin datos"
        ex, sym, first, limit = best
        since = first
        if coin in old.columns and old[coin].notna().any():
            since = int(old[coin].dropna().index[-1].timestamp() * 1000)  # última hora guardada (cierre)
        s = fetch_hourly(ex, sym, max(since, start_ms), limit)
        return coin, s, ex.id

    with cf.ThreadPoolExecutor(3) as pool:
        got = list(pool.map(one, coins))
    cols = {}
    for coin, s, src in got:
        prev = old[coin].dropna() if coin in old.columns else pd.Series(dtype=float)
        cols[coin] = s.combine_first(prev) if len(prev) else s
        print(f"  {coin}: {src}, {len(s)} velas nuevas")
    P = pd.DataFrame(cols).sort_index()
    P = P[[c for c in coins if c in P.columns]]
    DATA_DIR.mkdir(exist_ok=True)
    P.to_csv(path)
    return P


def hourly_to_daily(H: pd.DataFrame) -> pd.DataFrame:
    """Cierre diario = precio de las 00:00 UTC del día siguiente (vela diaria completa).

    La fila D es el cierre del día D, igual que en el resto del laboratorio.
    """
    mid = H[H.index.hour == 0]
    mid.index = mid.index.normalize() - pd.Timedelta(days=1)
    return mid
