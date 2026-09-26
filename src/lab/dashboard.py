"""Construye dashboard/index.html incrustando el último estado del bot como datos de respaldo.

    python -m lab.dashboard

La página publicada lee en vivo state/ desde GitHub; lo incrustado solo se muestra si no puede.
"""
from __future__ import annotations

import json

from .data import ROOT


def build() -> str:
    tpl = (ROOT / "dashboard" / "template.html").read_text()
    st = ROOT / "state"
    snap = json.loads((st / "snapshot.json").read_text()) if (st / "snapshot.json").exists() else {"sleeves": {}}
    fb = {
        "generated": snap.get("generated_utc", ""),
        "snapshot": snap,
        "equity": (st / "equity.csv").read_text() if (st / "equity.csv").exists() else "",
        "trades": (st / "trades.csv").read_text() if (st / "trades.csv").exists() else "",
        "analysis": json.loads((st / "analysis.json").read_text()) if (st / "analysis.json").exists() else None,
    }
    payload = json.dumps(fb, ensure_ascii=False).replace("</", "<\\/")
    html = tpl.replace("__FALLBACK__", payload)
    (ROOT / "dashboard" / "index.html").write_text(html)
    return str(ROOT / "dashboard" / "index.html")


if __name__ == "__main__":
    print(build())
