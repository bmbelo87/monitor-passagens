"""Hourly fare monitor using SerpApi's Google Flights engine."""

from __future__ import annotations

import itertools
import argparse
import logging
import os
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "fares.sqlite3"
LOG = logging.getLogger("fare-monitor")
SERPAPI_URL = "https://serpapi.com/search.json"


def settings() -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    origins = [x.strip().upper() for x in os.getenv("ORIGIN_AIRPORTS", "GRU,CGH").split(",") if x.strip()]
    if not origins:
        raise ValueError("ORIGIN_AIRPORTS precisa conter ao menos um aeroporto.")
    return {
        "api_key": os.getenv("SERPAPI_API_KEY", "").strip(),
        "telegram_token": os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        "origins": origins,
        "destination": os.getenv("DESTINATION_AIRPORT", "CNF").strip().upper(),
        "departure": date.fromisoformat(os.getenv("DEPARTURE_DATE", "2026-12-16")),
        "return": date.fromisoformat(os.getenv("RETURN_DATE", "2026-12-20")),
        "window": max(0, int(os.getenv("DATE_WINDOW_DAYS", "1"))),
        "interval": max(1, int(os.getenv("POLL_INTERVAL_MINUTES", "60"))),
        "max_price": float(os.getenv("MAX_PRICE_BRL", "500")),
        "adults": max(1, int(os.getenv("ADULTS", "1"))),
    }


def init_db() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS fares (
            id INTEGER PRIMARY KEY, checked_at TEXT NOT NULL, origin TEXT NOT NULL,
            destination TEXT NOT NULL, departure TEXT NOT NULL, return_date TEXT NOT NULL,
            amount REAL NOT NULL, currency TEXT NOT NULL, airline TEXT, outbound TEXT,
            inbound TEXT, stops_out INTEGER, stops_in INTEGER, offer_id TEXT
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS fare_lookup ON fares(origin,destination,departure,return_date,amount)")


def telegram(cfg: dict[str, Any], message: str) -> None:
    token, chat_id = cfg["telegram_token"], cfg["telegram_chat_id"]
    if not token or not chat_id:
        LOG.info("Telegram ainda não configurado; alerta não enviado.")
        return
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True}, timeout=20,
        )
        if not response.ok:
            raise RuntimeError(f"Telegram HTTP {response.status_code}")
    except Exception as exc:
        # Do not print request exception text: it may contain the bot token URL.
        LOG.error("Não foi possível enviar o alerta ao Telegram (%s).", type(exc).__name__)


def dates_to_check(cfg: dict[str, Any]) -> list[tuple[date, date]]:
    window = cfg["window"]
    departures = [cfg["departure"] + timedelta(days=i) for i in range(-window, window + 1)]
    returns = [cfg["return"] + timedelta(days=i) for i in range(-window, window + 1)]
    return [(out, back) for out, back in itertools.product(departures, returns) if back > out]


def parse_offer(item: dict[str, Any], departure: date, return_date: date) -> dict[str, Any] | None:
    flights = item.get("flights", [])
    if not flights or not isinstance(item.get("price"), (int, float)):
        return None
    # Google Flights lists both directions in a single round-trip result.
    arrival_index = next((i for i, leg in enumerate(flights)
                          if leg.get("arrival_airport", {}).get("id") == "CNF"), None)
    if arrival_index is None:
        # Fall back to splitting the returned itinerary by travel date.
        arrival_index = next((i for i, leg in enumerate(flights)
                              if (leg.get("departure_airport", {}).get("time", "")[:10] == return_date.isoformat())), len(flights) // 2 - 1)
    outbound = flights[:arrival_index + 1]
    inbound = flights[arrival_index + 1:]
    if not outbound or not inbound:
        return None

    def leg_text(segments: list[dict[str, Any]]) -> str:
        first = segments[0]
        last = segments[-1]
        start = first.get("departure_airport", {}).get("time", "")
        end = last.get("arrival_airport", {}).get("time", "")
        start_time = start[-5:] if len(start) >= 16 else start
        end_time = end[-5:] if len(end) >= 16 else end
        return f"{start_time}–{end_time} ({len(segments)-1} escala(s))"

    origin = outbound[0].get("departure_airport", {}).get("id", "")
    airlines = list(dict.fromkeys(x.get("airline", "") for x in flights if x.get("airline")))
    return {
        "origin": origin, "departure": departure.isoformat(), "return": return_date.isoformat(),
        "amount": float(item["price"]), "currency": "BRL", "airline": ", ".join(airlines) or "companhia não informada",
        "outbound": leg_text(outbound), "inbound": leg_text(inbound),
        "stops_out": len(outbound)-1, "stops_in": len(inbound)-1,
        "offer_id": str(item.get("departure_token", "")),
    }


def search(cfg: dict[str, Any], departure: date, return_date: date) -> list[dict[str, Any]]:
    if not cfg["api_key"]:
        raise RuntimeError("Configure SERPAPI_API_KEY no arquivo .env.")
    params = {
        "engine": "google_flights", "api_key": cfg["api_key"],
        "departure_id": ",".join(cfg["origins"]), "arrival_id": cfg["destination"],
        "outbound_date": departure.isoformat(), "return_date": return_date.isoformat(),
        "type": 1, "adults": cfg["adults"], "currency": "BRL", "gl": "br", "hl": "pt-BR",
    }
    try:
        response = requests.get(SERPAPI_URL, params=params, timeout=90)
    except requests.RequestException as exc:
        raise RuntimeError(f"Falha de conexão com a SerpApi ({type(exc).__name__}).") from None
    if not response.ok:
        raise RuntimeError(f"SerpApi retornou HTTP {response.status_code}.")
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError("SerpApi não concluiu a busca; confira chave e cota no painel.")
    results = []
    for item in payload.get("best_flights", []) + payload.get("other_flights", []):
        parsed = parse_offer(item, departure, return_date)
        if parsed:
            results.append(parsed)
    return results


def store_and_alert(cfg: dict[str, Any], offers: list[dict[str, Any]], startup: bool = False) -> None:
    if not offers:
        LOG.info("Nenhuma oferta recebida nesta rodada.")
        with sqlite3.connect(DB_PATH) as db:
            low = db.execute("SELECT amount, airline FROM fares ORDER BY amount LIMIT 1").fetchone()
        if low:
            telegram(cfg, f"🔎 Nenhuma oferta encontrada, valor mais baixo atualmente: R$ {low[0]:.2f} | {low[1]}")
        else:
            telegram(cfg, "🔎 Nenhuma oferta encontrada nesta busca.")
        return
    best = min(offers, key=lambda x: x["amount"])
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sqlite3.connect(DB_PATH) as db:
        (previous_low,) = db.execute("SELECT MIN(amount) FROM fares").fetchone()
        db.execute(
            "INSERT INTO fares (checked_at,origin,destination,departure,return_date,amount,currency,airline,outbound,inbound,stops_out,stops_in,offer_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (checked_at, best["origin"], cfg["destination"], best["departure"], best["return"], best["amount"], best["currency"], best["airline"], best["outbound"], best["inbound"], best["stops_out"], best["stops_in"], best["offer_id"]),
        )
        db.commit()
    LOG.info("Menor preço agora: R$ %.2f (%s).", best["amount"], best["airline"])
    lines = [f"✈️ R$ {best['amount']:.2f} | {best['airline']}"]
    if previous_low is not None and best["amount"] < previous_low - 0.009:
        lines.insert(0, "🔥 Menor valor")
    telegram(cfg, "\n".join(lines))


def run_once(cfg: dict[str, Any], startup: bool = False) -> None:
    init_db()
    offers = []
    completed_searches = 0
    for departure, return_date in dates_to_check(cfg):
        try:
            offers.extend(search(cfg, departure, return_date))
            completed_searches += 1
        except RuntimeError as exc:
            # Errors are deliberately sanitized; never log a URL containing the API key.
            LOG.warning("Busca %s/%s não concluída: %s", departure, return_date, str(exc))
            if "chave" in str(exc).lower() or "cota" in str(exc).lower():
                break
        time.sleep(0.5)
    if startup and completed_searches == 0:
        telegram(cfg, "⚠️ Não consegui concluir a busca inicial de passagens.\n"
                 "Confira a conexão, a chave e a cota da SerpApi. Vou tentar novamente no próximo intervalo.")
        return
    store_and_alert(cfg, offers, startup=startup)


def has_fare_history() -> bool:
    if not DB_PATH.exists():
        return False
    with sqlite3.connect(DB_PATH) as db:
        try:
            return db.execute("SELECT 1 FROM fares LIMIT 1").fetchone() is not None
        except sqlite3.OperationalError:
            return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor de preços de passagens aéreas")
    parser.add_argument("--once", action="store_true", help="faz uma busca e encerra (ideal para GitHub Actions)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = settings()
    init_db()
    searches_per_round = len(dates_to_check(cfg))
    LOG.info("Monitor SerpApi iniciado: %s → %s; %s buscas por rodada; intervalo %s min; janela ±%s dia(s).",
             ",".join(cfg["origins"]), cfg["destination"], searches_per_round, cfg["interval"], cfg["window"])
    if args.once:
        try:
            run_once(cfg, startup=not has_fare_history())
        except Exception as exc:
            LOG.error("A rodada falhou (%s).", type(exc).__name__)
            raise
        return
    first_run = True
    while True:
        started = time.monotonic()
        try:
            run_once(cfg, startup=first_run)
        except Exception as exc:
            LOG.error("A rodada falhou (%s).", type(exc).__name__)
        first_run = False
        time.sleep(max(10, cfg["interval"] * 60 - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
