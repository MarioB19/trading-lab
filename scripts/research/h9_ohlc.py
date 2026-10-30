"""H9: descarga velas diarias (UTC) de OKX, pares USDT, para las 16 monedas de Bitso.

    python scripts/research/h9_ohlc.py [--out data/crypto_ohlc_okx.csv] [--start 2018-01-01]

Escribe un CSV largo: date, asset, open, high, low, close, volume. Solo investigación (H9);
no toca el bot. Ver reports/h9_parabolic_sar_preregistro.md.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from lab.research_multi import BITSO_TRADABLE  # noqa: E402

URL = "https://www.okx.com/api/v5/market/history-candles"
DAY_MS = 86_400_000


def fetch_asset(asset: str, start: pd.Timestamp, session: requests.Session) -> pd.DataFrame:
    """Pagina hacia atrás con `after` (más antiguo que ese ms) hasta pasar `start` o quedarse sin datos."""
    rows: list[list] = []
    after = int((pd.Timestamp.now('UTC').normalize() + pd.Timedelta(days=1)).timestamp() * 1000)
    start_ms = int(start.tz_localize("UTC").timestamp() * 1000) if start.tzinfo is None else int(start.timestamp() * 1000)
    while True:
        for attempt in range(6):
            r = session.get(URL, params={"instId": f"{asset}-USDT", "bar": "1D", "limit": 100, "after": after}, timeout=30)
            if r.status_code == 200 and r.json().get("code") == "0":
                break
            time.sleep(1.5 * (attempt + 1))
        else:
            raise RuntimeError(f"OKX no respondió para {asset}: {r.status_code} {r.text[:120]}")
        data = r.json()["data"]
        if not data:
            break
        rows.extend(data)
        oldest = int(data[-1][0])
        if oldest <= start_ms or len(data) < 100:
            break
        after = oldest
        time.sleep(0.12)  # 20 peticiones / 2 s
    if not rows:
        return pd.DataFrame(columns=["date", "asset", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows).iloc[:, :6]
    df.columns = ["ts", "open", "high", "low", "close", "volume"]
    df["date"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms", utc=True).dt.tz_localize(None).dt.normalize()
    df = df.drop(columns="ts").astype({c: float for c in ["open", "high", "low", "close", "volume"]})
    df["asset"] = asset
    df = df[df["date"] >= (start.tz_localize(None) if start.tzinfo else start)]
    return df.drop_duplicates("date").sort_values("date")[["date", "asset", "open", "high", "low", "close", "volume"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/crypto_ohlc_okx.csv")
    ap.add_argument("--start", default="2018-01-01")
    a = ap.parse_args()
    start = pd.Timestamp(a.start)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    with requests.Session() as s:
        for asset in BITSO_TRADABLE:
            df = fetch_asset(asset, start, s)
            print(f"{asset}: {len(df)} días" + (f" ({df['date'].min().date()} → {df['date'].max().date()})" if len(df) else ""))
            frames.append(df)
    full = pd.concat(frames, ignore_index=True)
    full.to_csv(out, index=False)
    print(f"escrito {out} con {len(full)} filas")


if __name__ == "__main__":
    main()
