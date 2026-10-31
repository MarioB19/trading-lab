"""Catálogo 3: descarga las series exógenas (sentimiento, on-chain, stablecoins) a data/exog_*.csv.

    PYTHONPATH=src python scripts/research/catalogo3_data.py

Fuentes públicas, sin llaves: alternative.me (Fear & Greed), CoinMetrics community (BTC: MVRV, direcciones activas,
BTC en exchanges, hash rate, transacciones), DefiLlama (oferta total de stablecoins). Solo investigación.
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data"
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 trading-lab-research"


def fng() -> pd.DataFrame:
    d = S.get("https://api.alternative.me/fng/?limit=0&format=json", timeout=30).json()["data"]
    df = pd.DataFrame({"date": pd.to_datetime([int(x["timestamp"]) for x in d], unit="s"),
                       "fng": [float(x["value"]) for x in d]}).sort_values("date")
    return df.set_index("date")


def coinmetrics(asset="btc") -> pd.DataFrame:
    metrics = "CapMVRVCur,AdrActCnt,SplyExNtv,HashRate,TxCnt,CapMrktCurUSD"
    url = (f"https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets={asset}&metrics={metrics}"
           f"&frequency=1d&start_time=2015-01-01&page_size=10000")
    rows = []
    while url:
        j = S.get(url, timeout=60).json()
        rows += j["data"]
        url = j.get("next_page_url")
        time.sleep(0.3)
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["time"]).dt.tz_localize(None).dt.normalize()
    keep = [c for c in df.columns if c in metrics.split(",")]
    out = df.set_index("date")[keep].astype(float)
    out.columns = [f"{asset}_{c}" for c in out.columns]
    return out


def stablecoins() -> pd.DataFrame:
    d = S.get("https://stablecoins.llama.fi/stablecoincharts/all", timeout=60).json()
    df = pd.DataFrame({"date": pd.to_datetime([int(x["date"]) for x in d], unit="s"),
                       "stables_usd": [float((x.get("totalCirculatingUSD") or {}).get("peggedUSD", float("nan"))) for x in d]})
    return df.set_index("date").sort_index()


def main() -> None:
    OUT.mkdir(exist_ok=True)
    frames = {"exog_fng": fng(), "exog_cm_btc": coinmetrics("btc"), "exog_stables": stablecoins()}
    for name, df in frames.items():
        df.to_csv(OUT / f"{name}.csv")
        print(name, df.shape, str(df.index.min().date()), "→", str(df.index.max().date()), list(df.columns))


if __name__ == "__main__":
    main()
