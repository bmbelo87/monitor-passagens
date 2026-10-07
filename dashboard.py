"""Gera docs/index.html, um painel estático com o histórico de tarifas."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from monitor import DB_PATH, ROOT, ROUTE_FILTER, init_db, route_params, settings

OUT_PATH = ROOT / "docs" / "index.html"
TEMPLATE_PATH = ROOT / "dashboard_template.html"


def load_fares(cfg: dict) -> list[dict]:
    init_db()
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT checked_at, origin, destination, departure, return_date, amount, airline,"
            " outbound, inbound, stops_out, stops_in FROM fares WHERE " + ROUTE_FILTER + " ORDER BY checked_at",
            route_params(cfg),
        ).fetchall()
    return [dict(r) for r in rows]


def build() -> Path:
    cfg = settings()
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "origins": cfg["origins"],
        "destination": cfg["destination"],
        "departure": cfg["departure"].isoformat(),
        "return": cfg["return"].isoformat(),
        "interval": cfg["interval"],
        "fares": load_fares(cfg),
    }
    # "</" escaped so the JSON can never close the <script> tag.
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE_PATH.read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")
    return OUT_PATH


if __name__ == "__main__":
    print(f"Painel gerado em {build()}")
