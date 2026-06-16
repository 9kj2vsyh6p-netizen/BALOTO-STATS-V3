#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BALOTO STATS V3 — Scraper de resultados históricos.

Descarga resultados de Baloto y Baloto Revancha desde la API interna de
baloto.com, los normaliza y los guarda en data/resultados.json aplicando un
merge inteligente anti-duplicados.

Fuente de datos
---------------
API (no oficial) usada por baloto.com, documentada por ingeniería inversa:

    POST https://api-baloto-prod.baloto.com/petition
    body: {"type": "/GameResultByDate", "parameters": {"gameDate": "YYYY/MM"}}

Devuelve, por mes, una lista de objetos con baloto1..baloto5 (+ baloto6 =
superbalota) y revancha1..revancha5 (+ revancha6 = superbalota). MiLoto NO
está cubierto por esta API; se mantiene aparte.

Modos de uso
------------
    python scraper.py                 # Actualización incremental (últimos meses)
    python scraper.py --rebuild       # Reconstrucción completa del histórico
    python scraper.py --audit         # Diagnóstico mes a mes (no escribe datos)
    python scraper.py --game baloto   # Limita a un juego concreto
    python scraper.py --since 2017/01 # Punto de partida para el rebuild
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:  # pragma: no cover
    print("Falta 'requests'. Instala con: pip install -r scripts/requirements.txt", file=sys.stderr)
    raise


# --------------------------------------------------------------------------- #
# Configuración global
# --------------------------------------------------------------------------- #

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "resultados.json"
LOG_FILE = ROOT / "scripts" / "scraper.log"

GAMES = ("baloto", "revancha", "miloto")

GAME_RULES = {
    "baloto":   {"count": 5, "min": 1, "max": 43, "superbalota": True,  "sb_min": 1, "sb_max": 16},
    "revancha": {"count": 5, "min": 1, "max": 43, "superbalota": True,  "sb_min": 1, "sb_max": 16},
    "miloto":   {"count": 5, "min": 1, "max": 39, "superbalota": False, "sb_min": 0, "sb_max": 0},
}

REQUEST_TIMEOUT = 25
RETRY_TOTAL = 5
RETRY_BACKOFF = 1.5
THROTTLE_SECONDS = 0.4
USER_AGENT = "Mozilla/5.0 (compatible; BalotoStatsV3/2.0; statistical-research)"


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

def setup_logging(verbose: bool = True) -> logging.Logger:
    logger = logging.getLogger("baloto")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", "%Y-%m-%d %H:%M:%S")
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO if verbose else logging.WARNING)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    try:
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError:
        pass
    return logger


log = logging.getLogger("baloto")


# --------------------------------------------------------------------------- #
# Modelo de datos y validación
# --------------------------------------------------------------------------- #

@dataclass
class Draw:
    fecha: str
    sorteo: Optional[int]
    numeros: list
    superbalota: Optional[int]

    def to_dict(self) -> dict:
        return {"fecha": self.fecha, "sorteo": self.sorteo,
                "numeros": self.numeros, "superbalota": self.superbalota}

    def key_primary(self):
        return (self.fecha, int(self.sorteo)) if self.sorteo is not None else None

    def key_fallback(self):
        return (self.fecha, tuple(sorted(self.numeros)))


class ValidationError(Exception):
    pass


def validate(game: str, draw: Draw) -> None:
    rules = GAME_RULES[game]
    try:
        datetime.strptime(draw.fecha, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise ValidationError(f"fecha invalida: {draw.fecha!r}")
    nums = draw.numeros
    if not isinstance(nums, list) or len(nums) != rules["count"]:
        raise ValidationError(f"se esperaban {rules['count']} numeros, hay {len(nums) if nums else 0}")
    if len(set(nums)) != len(nums):
        raise ValidationError("numeros repetidos")
    for n in nums:
        if not isinstance(n, int) or not (rules["min"] <= n <= rules["max"]):
            raise ValidationError(f"numero fuera de rango [{rules['min']},{rules['max']}]: {n}")
    if rules["superbalota"]:
        sb = draw.superbalota
        if sb is None or not (rules["sb_min"] <= sb <= rules["sb_max"]):
            raise ValidationError(f"superbalota fuera de rango [{rules['sb_min']},{rules['sb_max']}]: {sb}")
    else:
        draw.superbalota = None


# --------------------------------------------------------------------------- #
# Cliente HTTP con reintentos
# --------------------------------------------------------------------------- #

def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=RETRY_TOTAL, connect=RETRY_TOTAL, read=RETRY_TOTAL,
        backoff_factor=RETRY_BACKOFF,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json",
                            "Accept-Language": "es-CO,es;q=0.9"})
    return session


# --------------------------------------------------------------------------- #
# Adaptadores de fuente
# --------------------------------------------------------------------------- #

class Source:
    name = "base"

    def __init__(self, session: requests.Session):
        self.session = session

    def supports(self, game: str) -> bool:
        return True

    def fetch_month(self, game: str, year: int, month: int) -> list:
        raise NotImplementedError


class BalotoApiSource(Source):
    """API interna de baloto.com (Baloto + Revancha). No oficial."""
    name = "api-baloto-prod"
    ENDPOINT = "https://api-baloto-prod.baloto.com/petition"

    def __init__(self, session: requests.Session):
        super().__init__(session)
        self._cache = {}

    def supports(self, game: str) -> bool:
        return game in ("baloto", "revancha")

    def _fetch_raw(self, year: int, month: int) -> dict:
        key = (year, month)
        if key in self._cache:
            return self._cache[key]
        body = {"type": "/GameResultByDate", "parameters": {"gameDate": f"{year:04d}/{month:02d}"}}
        empty = {"baloto": [], "revancha": []}
        try:
            resp = self.session.post(self.ENDPOINT, json=body, timeout=REQUEST_TIMEOUT,
                                     headers={"Content-Type": "application/json",
                                              "Origin": "https://baloto.com",
                                              "Referer": "https://baloto.com/resultados"})
        except requests.RequestException as exc:
            log.warning("Fallo de red en API (%04d/%02d): %s", year, month, exc)
            self._cache[key] = empty
            return empty
        time.sleep(THROTTLE_SECONDS)
        if resp.status_code != 200:
            log.warning("HTTP %s en API (%04d/%02d)", resp.status_code, year, month)
            self._cache[key] = empty
            return empty
        try:
            rows = resp.json()
        except ValueError:
            log.warning("Respuesta no-JSON de la API (%04d/%02d)", year, month)
            self._cache[key] = empty
            return empty
        if isinstance(rows, dict):
            rows = rows.get("data", rows.get("result", rows.get("results", [])))
        baloto, revancha = [], []
        for r in rows or []:
            fecha = str(r.get("date") or "")[:10]
            sorteo = _to_int(r.get("sorteo"))
            try:
                b = [int(r["baloto1"]), int(r["baloto2"]), int(r["baloto3"]),
                     int(r["baloto4"]), int(r["baloto5"])]
                if any(b):
                    baloto.append(Draw(fecha=fecha, sorteo=sorteo, numeros=b,
                                       superbalota=_to_int(r.get("baloto6"))))
            except (KeyError, TypeError, ValueError):
                pass
            try:
                v = [int(r["revancha1"]), int(r["revancha2"]), int(r["revancha3"]),
                     int(r["revancha4"]), int(r["revancha5"])]
                if any(v):
                    revancha.append(Draw(fecha=fecha, sorteo=sorteo, numeros=v,
                                         superbalota=_to_int(r.get("revancha6"))))
            except (KeyError, TypeError, ValueError):
                pass
        self._cache[key] = {"baloto": baloto, "revancha": revancha}
        return self._cache[key]

    def fetch_month(self, game: str, year: int, month: int) -> list:
        if not self.supports(game):
            return []
        return self._fetch_raw(year, month).get(game, [])


class JsonEndpointSource(Source):
    """Fuente genérica: endpoint JSON propio (BALOTO_JSON_URL)."""
    name = "json-endpoint"

    def __init__(self, session: requests.Session, base_url: str):
        super().__init__(session)
        self.base_url = base_url.rstrip("?&")

    def fetch_month(self, game: str, year: int, month: int) -> list:
        sep = "&" if "?" in self.base_url else "?"
        url = f"{self.base_url}{sep}game={game}&year={year}&month={month:02d}"
        try:
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            log.warning("Fallo de red en %s: %s", url, exc)
            return []
        time.sleep(THROTTLE_SECONDS)
        if resp.status_code != 200:
            log.warning("HTTP %s en %s", resp.status_code, url)
            return []
        try:
            payload = resp.json()
        except ValueError:
            return []
        rows = payload if isinstance(payload, list) else payload.get("data", payload.get("results", []))
        out = []
        for r in rows:
            out.append(Draw(
                fecha=str(r.get("fecha") or r.get("date"))[:10],
                sorteo=_to_int(r.get("sorteo") or r.get("draw")),
                numeros=[int(x) for x in (r.get("numeros") or r.get("numbers") or [])],
                superbalota=_to_int(r.get("superbalota") or r.get("sb")),
            ))
        return out


def make_source(session: requests.Session) -> Source:
    json_url = os.environ.get("BALOTO_JSON_URL", "").strip()
    if json_url:
        log.info("Fuente: endpoint JSON propio (%s)", json_url)
        return JsonEndpointSource(session, json_url)
    log.info("Fuente: API baloto.com (Baloto + Revancha)")
    return BalotoApiSource(session)


# --------------------------------------------------------------------------- #
# Almacenamiento y merge anti-duplicados
# --------------------------------------------------------------------------- #

def load_store() -> dict:
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                store = json.load(f)
        except (ValueError, OSError) as exc:
            log.error("No se pudo leer %s (%s). Se reinicia.", DATA_FILE, exc)
            store = {}
    else:
        store = {}
    for g in GAMES:
        store.setdefault(g, [])
    store.setdefault("_meta", {})
    store["_meta"].setdefault("sample_games", list(GAMES))
    return store


def save_store(store: dict, made_real=None) -> None:
    meta = store["_meta"]
    meta["actualizado"] = datetime.now().isoformat(timespec="seconds")
    meta["cobertura"] = coverage_summary(store)
    sg = set(meta.get("sample_games", list(GAMES)))
    for g in (made_real or []):
        sg.discard(g)
    meta["sample_games"] = sorted(sg)
    meta.pop("source", None)  # se reemplaza por sample_games (por juego)
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(DATA_FILE)
    log.info("Guardado %s", DATA_FILE)


def build_index(rows):
    primary, fallback = set(), set()
    for r in rows:
        if r.get("sorteo") is not None:
            primary.add((r["fecha"], int(r["sorteo"])))
        fallback.add((r["fecha"], tuple(sorted(r["numeros"]))))
    return primary, fallback


def merge_game(store_rows, new_draws):
    primary, fallback = build_index(store_rows)
    added = dup = 0
    for d in new_draws:
        kp, kf = d.key_primary(), d.key_fallback()
        if (kp is not None and kp in primary) or kf in fallback:
            dup += 1
            continue
        store_rows.append(d.to_dict())
        if kp is not None:
            primary.add(kp)
        fallback.add(kf)
        added += 1
    store_rows.sort(key=lambda r: (r["fecha"], r.get("sorteo") or 0))
    return added, dup


def coverage_summary(store):
    out = {}
    for g in GAMES:
        rows = store.get(g, [])
        if rows:
            fechas = sorted(r["fecha"] for r in rows)
            out[g] = {"desde": fechas[0], "hasta": fechas[-1], "total": len(rows)}
        else:
            out[g] = {"desde": None, "hasta": None, "total": 0}
    return out


# --------------------------------------------------------------------------- #
# Orquestación
# --------------------------------------------------------------------------- #

def month_range(start, end):
    (sy, sm), (ey, em) = start, end
    y, m = sy, sm
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m > 12:
            m, y = 1, y + 1


def process(games, start, end, audit, write, reset):
    session = build_session()
    source = make_source(session)
    store = load_store()
    report = {g: [] for g in games}
    made_real = []
    total_added = 0

    # En rebuild: limpia los juegos soportados por la fuente para no mezclar
    # datos de muestra antiguos con datos reales.
    if reset and not audit:
        for g in games:
            if source.supports(g):
                store[g] = []
                log.info("rebuild: %s reiniciado", g)

    for game in games:
        if not source.supports(game):
            log.info("=== %s === (no cubierto por la fuente; se conserva)", game.upper())
            continue
        log.info("=== %s ===", game.upper())
        for (y, m) in month_range(start, end):
            try:
                raw = source.fetch_month(game, y, m)
            except Exception as exc:
                log.error("Error en %s %04d/%02d: %s", game, y, m, exc)
                raw = []
            accepted, discarded, reasons = [], 0, {}
            for d in raw:
                try:
                    validate(game, d)
                    accepted.append(d)
                except ValidationError as ve:
                    discarded += 1
                    reasons[str(ve)] = reasons.get(str(ve), 0) + 1
            added = 0
            if not audit and write:
                added, _ = merge_game(store[game], accepted)
                total_added += added
                if added:
                    made_real.append(game)
            report[game].append({"mes": f"{y:04d}/{m:02d}", "api": len(raw),
                                  "aceptados": len(accepted), "descartados": discarded,
                                  "razones": reasons, "agregados": added})
            if raw or audit:
                log.info("%s %04d/%02d  API:%d  Acept:%d  Desc:%d  Agreg:%d",
                         game, y, m, len(raw), len(accepted), discarded, added)

    if not audit and write:
        save_store(store, made_real=sorted(set(made_real)))
        log.info("Total agregados en esta corrida: %d", total_added)

    return {"report": report, "cobertura": coverage_summary(store)}


def print_audit(result):
    print("\n" + "=" * 56)
    print("  DIAGNÓSTICO BALOTO STATS V3")
    print("=" * 56)
    for game, entries in result["report"].items():
        active = [e for e in entries if e["api"] > 0 or e["descartados"] > 0]
        if not active:
            continue
        print(f"\n### {game.upper()}")
        for e in active:
            print(f"\n{e['mes']}")
            print(f"  API:         {e['api']}")
            print(f"  Aceptados:   {e['aceptados']}")
            print(f"  Descartados: {e['descartados']}")
            for r, c in e["razones"].items():
                print(f"     - {r}: {c}")
            print(f"  Agregados:   {e['agregados']}")
    print("\n" + "-" * 56)
    print("  COBERTURA DETECTADA")
    print("-" * 56)
    for g, c in result["cobertura"].items():
        if c["total"]:
            print(f"  {g.capitalize():9} desde {c['desde']}  hasta {c['hasta']}  total {c['total']}")
        else:
            print(f"  {g.capitalize():9} sin datos")
    print()


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #

def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_yyyymm(s, default):
    if not s:
        return default
    m = re.match(r"(\d{4})[/\-](\d{1,2})", s)
    if not m:
        raise SystemExit(f"Formato invalido (use YYYY/MM): {s!r}")
    return int(m.group(1)), int(m.group(2))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Scraper de resultados Baloto/Revancha/MiLoto")
    parser.add_argument("--rebuild", action="store_true", help="Reconstrucción completa")
    parser.add_argument("--audit", action="store_true", help="Diagnóstico mes a mes (no escribe)")
    parser.add_argument("--game", choices=list(GAMES) + ["all"], default="all")
    parser.add_argument("--since", default="", help="Inicio del rebuild YYYY/MM (ej: 2017/01)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(verbose=not args.quiet)
    today = date.today()
    end = (today.year, today.month)

    if args.rebuild or args.audit:
        default_start = parse_yyyymm(args.since, (2017, 1))
    else:
        ym = end[0] * 12 + (end[1] - 1) - 2
        default_start = (ym // 12, ym % 12 + 1)

    games = list(GAMES) if args.game == "all" else [args.game]
    log.info("Modo: %s | Juegos: %s | Rango: %04d/%02d -> %04d/%02d",
             "audit" if args.audit else ("rebuild" if args.rebuild else "incremental"),
             ",".join(games), *default_start, *end)

    result = process(games, default_start, end, audit=args.audit,
                     write=not args.audit, reset=args.rebuild)
    if args.audit:
        print_audit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
