#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BALOTO STATS V3 — Scraper de resultados históricos.

Origen de datos modernizado:
  1) PRIMARIO: API interna de baloto.com (no oficial)
         POST https://api-baloto-prod.baloto.com/petition
         tipos: /LastGameResult, /GameResultByDate, /GameWithCondition
     Cubre Baloto + Revancha (vienen juntos por sorteo).
  2) FALLBACK: scraping HTML best-effort de baloto.com (si la API falla).
  3) OPCIONAL: endpoint JSON propio vía BALOTO_JSON_URL.

Compatibilidad: escribe data/resultados.json con el MISMO formato de siempre:
  {"baloto":[...], "revancha":[...], "miloto":[...], "_meta":{...}}
  registro: {"fecha":"YYYY-MM-DD","sorteo":int|null,"numeros":[5],"superbalota":int|null}

Modos:
  python scraper.py                 # actualización incremental
  python scraper.py --rebuild       # reconstrucción completa
  python scraper.py --audit         # diagnóstico mes a mes (no escribe)
  python scraper.py --probe         # PRUEBA: llama /LastGameResult y muestra el JSON
  python scraper.py --game baloto   # limita a un juego
  python scraper.py --since 2017/01 # punto de partida del rebuild
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
from typing import Optional

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:  # pragma: no cover
    print("Falta 'requests'. Instala: pip install -r scripts/requirements.txt", file=sys.stderr)
    raise

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False


# --------------------------------------------------------------------------- #
# Configuración
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
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

API_ENDPOINT = "https://api-baloto-prod.baloto.com/petition"
API_TYPES = ("/LastGameResult", "/GameResultByDate", "/GameWithCondition")
HTML_URLS = {
    "baloto":   "https://baloto.com/resultados",
    "revancha": "https://baloto.com/resultados",
    "miloto":   "https://baloto.com/miloto/resultados",
}


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

def setup_logging(verbose: bool = True, debug: bool = False) -> logging.Logger:
    logger = logging.getLogger("baloto")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", "%Y-%m-%d %H:%M:%S")
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG if debug else (logging.INFO if verbose else logging.WARNING))
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
# Modelo y validación
# --------------------------------------------------------------------------- #

@dataclass
class Draw:
    fecha: str
    sorteo: Optional[int]
    numeros: list
    superbalota: Optional[int]

    def to_dict(self):
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
# HTTP
# --------------------------------------------------------------------------- #

def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=RETRY_TOTAL, connect=RETRY_TOTAL, read=RETRY_TOTAL,
                  backoff_factor=RETRY_BACKOFF, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset(["GET", "POST"]), raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*",
                            "Accept-Language": "es-CO,es;q=0.9"})
    return session


# --------------------------------------------------------------------------- #
# Helpers de parseo de la API
# --------------------------------------------------------------------------- #

def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _parse_api_records(rows) -> dict:
    """Convierte registros de la API en {'baloto':[Draw], 'revancha':[Draw]}."""
    baloto, revancha = [], []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        fecha = str(r.get("date") or r.get("fecha") or "")[:10]
        sorteo = _to_int(r.get("sorteo") or r.get("draw"))
        try:
            b = [int(r["baloto1"]), int(r["baloto2"]), int(r["baloto3"]),
                 int(r["baloto4"]), int(r["baloto5"])]
            if any(b):
                baloto.append(Draw(fecha, sorteo, b, _to_int(r.get("baloto6"))))
        except (KeyError, TypeError, ValueError):
            pass
        try:
            v = [int(r["revancha1"]), int(r["revancha2"]), int(r["revancha3"]),
                 int(r["revancha4"]), int(r["revancha5"])]
            if any(v):
                revancha.append(Draw(fecha, sorteo, v, _to_int(r.get("revancha6"))))
        except (KeyError, TypeError, ValueError):
            pass
    return {"baloto": baloto, "revancha": revancha}


def _unwrap(payload):
    """Devuelve la lista de registros sin importar cómo venga envuelta."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("data", "result", "results", "games", "items"):
            if isinstance(payload.get(k), list):
                return payload[k]
        # a veces el resultado viene como un único objeto
        return [payload]
    return []


# --------------------------------------------------------------------------- #
# Fuentes
# --------------------------------------------------------------------------- #

class Source:
    name = "base"

    def __init__(self, session):
        self.session = session

    def supports(self, game):
        return True

    def fetch_month(self, game, year, month):
        raise NotImplementedError


class BalotoApiSource(Source):
    """API interna de baloto.com — Baloto + Revancha. No oficial."""
    name = "api-baloto-prod"

    def __init__(self, session):
        super().__init__(session)
        self._cache = {}

    def supports(self, game):
        return game in ("baloto", "revancha")

    # --- petición de bajo nivel con logging detallado ---------------------- #
    def _post(self, body, label=""):
        log.debug("POST %s  type=%s  body=%s", API_ENDPOINT, body.get("type"), json.dumps(body))
        t0 = time.time()
        try:
            resp = self.session.post(
                API_ENDPOINT, json=body, timeout=REQUEST_TIMEOUT,
                headers={"Content-Type": "application/json",
                         "Origin": "https://baloto.com",
                         "Referer": "https://baloto.com/"})
        except requests.RequestException as exc:
            log.warning("API %s -> fallo de red: %s", label or body.get("type"), exc)
            return None, None, ""
        dt = (time.time() - t0) * 1000
        time.sleep(THROTTLE_SECONDS)
        raw = resp.text or ""
        log.debug("API %s -> HTTP %s  %.0fms  %d bytes", label or body.get("type"),
                  resp.status_code, dt, len(raw))
        if resp.status_code != 200:
            log.warning("API %s -> HTTP %s", label or body.get("type"), resp.status_code)
            log.debug("cuerpo (300): %s", raw[:300])
            return resp.status_code, None, raw
        try:
            payload = resp.json()
        except ValueError:
            log.warning("API %s -> respuesta no-JSON", label or body.get("type"))
            log.debug("cuerpo (300): %s", raw[:300])
            return resp.status_code, None, raw
        return resp.status_code, payload, raw

    # --- /LastGameResult ---------------------------------------------------- #
    def fetch_last(self):
        status, payload, _ = self._post({"type": "/LastGameResult"}, "/LastGameResult")
        if payload is None:
            return None
        return _parse_api_records(_unwrap(payload))

    # --- /GameResultByDate (por mes), con caché ----------------------------- #
    def _fetch_raw(self, year, month):
        key = (year, month)
        if key in self._cache:
            return self._cache[key]
        body = {"type": "/GameResultByDate", "parameters": {"gameDate": f"{year:04d}/{month:02d}"}}
        status, payload, _ = self._post(body, f"/GameResultByDate {year:04d}/{month:02d}")
        parsed = _parse_api_records(_unwrap(payload)) if payload is not None else {"baloto": [], "revancha": []}
        self._cache[key] = parsed
        return parsed

    def fetch_month(self, game, year, month):
        if not self.supports(game):
            return []
        return self._fetch_raw(year, month).get(game, [])

    # --- prueba de salud ---------------------------------------------------- #
    def probe(self):
        """POST /LastGameResult; imprime el JSON completo. Devuelve (ok, payload)."""
        log.info("PROBE -> POST %s  {\"type\": \"/LastGameResult\"}", API_ENDPOINT)
        status, payload, raw = self._post({"type": "/LastGameResult"}, "/LastGameResult")
        if payload is None:
            log.error("PROBE FALLIDO (status=%s). Cuerpo crudo (500): %s", status, raw[:500])
            return False, None
        log.info("PROBE OK (HTTP %s). JSON recibido:", status)
        print("\n" + "=" * 60)
        print("  RESPUESTA /LastGameResult")
        print("=" * 60)
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:8000])
        print("=" * 60)
        parsed = _parse_api_records(_unwrap(payload))
        log.info("Extraídos: %d baloto, %d revancha", len(parsed["baloto"]), len(parsed["revancha"]))
        for g in ("baloto", "revancha"):
            if parsed[g]:
                d = parsed[g][0]
                log.info("  %s ejemplo: %s sorteo=%s %s sb=%s",
                         g, d.fecha, d.sorteo, d.numeros, d.superbalota)
        return True, payload


class BalotoSiteSource(Source):
    """Fallback best-effort: parseo de HTML de baloto.com (marcado variable)."""
    name = "baloto.com-html"

    def supports(self, game):
        return True

    def fetch_month(self, game, year, month):
        if not _HAS_BS4:
            log.warning("HTML fallback no disponible (instala beautifulsoup4)")
            return []
        url = HTML_URLS[game]
        log.debug("HTML GET %s (%s %04d/%02d)", url, game, year, month)
        try:
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            log.warning("HTML %s -> fallo de red: %s", url, exc)
            return []
        time.sleep(THROTTLE_SECONDS)
        if resp.status_code != 200:
            log.warning("HTML %s -> HTTP %s", url, resp.status_code)
            return []
        draws = self._parse(resp.text, game)
        return [d for d in draws if _in_month(d.fecha, year, month)]

    @staticmethod
    def _parse(html, game):
        out = []
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)
        rules = GAME_RULES[game]
        for m in re.finditer(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", text):
            d, mo, y = (int(g) for g in m.groups())
            try:
                fecha = date(y, mo, d).isoformat()
            except ValueError:
                continue
            window = text[m.end():m.end() + 120]
            nums = [int(x) for x in re.findall(r"\b(\d{1,2})\b", window)]
            picks = [n for n in nums if rules["min"] <= n <= rules["max"]][: rules["count"]]
            if len(picks) == rules["count"]:
                sb = None
                if rules["superbalota"]:
                    tail = [n for n in nums[rules["count"]:] if rules["sb_min"] <= n <= rules["sb_max"]]
                    sb = tail[0] if tail else None
                out.append(Draw(fecha, None, picks, sb))
        return out


class JsonEndpointSource(Source):
    """Endpoint JSON propio (BALOTO_JSON_URL)."""
    name = "json-endpoint"

    def __init__(self, session, base_url):
        super().__init__(session)
        self.base_url = base_url.rstrip("?&")

    def fetch_month(self, game, year, month):
        sep = "&" if "?" in self.base_url else "?"
        url = f"{self.base_url}{sep}game={game}&year={year}&month={month:02d}"
        try:
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            log.warning("JSON %s -> fallo: %s", url, exc)
            return []
        time.sleep(THROTTLE_SECONDS)
        if resp.status_code != 200:
            return []
        try:
            payload = resp.json()
        except ValueError:
            return []
        out = []
        for r in _unwrap(payload):
            out.append(Draw(str(r.get("fecha") or r.get("date"))[:10],
                            _to_int(r.get("sorteo") or r.get("draw")),
                            [int(x) for x in (r.get("numeros") or r.get("numbers") or [])],
                            _to_int(r.get("superbalota") or r.get("sb"))))
        return out


class FallbackSource(Source):
    """Intenta la API primero; si no devuelve datos, recurre al HTML."""
    name = "api+html"

    def __init__(self, session):
        super().__init__(session)
        self.api = BalotoApiSource(session)
        self.html = BalotoSiteSource(session)
        self.api_healthy = None  # se decide en la primera prueba

    def supports(self, game):
        return self.api.supports(game) or self.html.supports(game)

    def ensure_health(self):
        if self.api_healthy is None:
            log.info("Comprobando salud de la API (/LastGameResult)…")
            self.api_healthy = self.api.fetch_last() is not None
            log.info("API %s", "OPERATIVA ✅" if self.api_healthy else "NO RESPONDE ❌ -> se usará HTML")
        return self.api_healthy

    def fetch_month(self, game, year, month):
        if self.ensure_health() and self.api.supports(game):
            data = self.api.fetch_month(game, year, month)
            if data:
                return data
            # API sana pero sin datos ese mes: no forzamos HTML (suele ser mes sin sorteos)
            return []
        # API caída -> fallback HTML
        return self.html.fetch_month(game, year, month)


def make_source(session):
    json_url = os.environ.get("BALOTO_JSON_URL", "").strip()
    if json_url:
        log.info("Fuente: endpoint JSON propio (%s)", json_url)
        return JsonEndpointSource(session, json_url)
    log.info("Fuente: API baloto.com con fallback HTML")
    return FallbackSource(session)


# --------------------------------------------------------------------------- #
# Almacenamiento y merge anti-duplicados
# --------------------------------------------------------------------------- #

def load_store():
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


def save_store(store, made_real=None):
    meta = store["_meta"]
    meta["actualizado"] = datetime.now().isoformat(timespec="seconds")
    meta["cobertura"] = coverage_summary(store)
    sg = set(meta.get("sample_games", list(GAMES)))
    for g in (made_real or []):
        sg.discard(g)
    meta["sample_games"] = sorted(sg)
    meta.pop("source", None)
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

    for game in games:
        if not source.supports(game):
            log.info("=== %s === (no cubierto por la fuente; se conserva)", game.upper())
            continue
        log.info("=== %s ===", game.upper())
        target = [] if (reset and not audit) else store[game]
        fetched_any = False
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
                added, _ = merge_game(target, accepted)
                total_added += added
                if accepted:
                    fetched_any = True
            report[game].append({"mes": f"{y:04d}/{m:02d}", "api": len(raw),
                                  "aceptados": len(accepted), "descartados": discarded,
                                  "razones": reasons, "agregados": added})
            if raw or audit:
                log.info("%s %04d/%02d  Fuente:%d  Acept:%d  Desc:%d  Agreg:%d",
                         game, y, m, len(raw), len(accepted), discarded, added)

        if not audit and write:
            if reset:
                if fetched_any and target:
                    store[game] = target
                    made_real.append(game)
                    log.info("%s: %d sorteos reales cargados", game, len(target))
                else:
                    log.warning("%s: la fuente no devolvió datos reales; "
                                "se conservan los datos previos", game)
            elif target is store[game] and any(e["agregados"] for e in report[game]):
                made_real.append(game)

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
            print(f"  Fuente:      {e['api']}")
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

def _in_month(fecha, year, month):
    try:
        dt = datetime.strptime(fecha, "%Y-%m-%d")
    except (ValueError, TypeError):
        return False
    return dt.year == year and dt.month == month


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
    parser = argparse.ArgumentParser(description="Scraper Baloto/Revancha/MiLoto")
    parser.add_argument("--rebuild", action="store_true", help="Reconstrucción completa")
    parser.add_argument("--audit", action="store_true", help="Diagnóstico mes a mes (no escribe)")
    parser.add_argument("--probe", action="store_true", help="Prueba /LastGameResult y muestra el JSON")
    parser.add_argument("--game", choices=list(GAMES) + ["all"], default="all")
    parser.add_argument("--since", default="", help="Inicio del rebuild YYYY/MM (ej: 2017/01)")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--debug", action="store_true", help="Logging detallado (DEBUG)")
    args = parser.parse_args(argv)

    setup_logging(verbose=not args.quiet, debug=args.debug)

    # Modo prueba: solo verifica la API y muestra el JSON, no escribe nada.
    if args.probe:
        session = build_session()
        api = BalotoApiSource(session)
        ok, _ = api.probe()
        if ok:
            print("\n✅ La API respondió. Puedes usar --rebuild para cargar el histórico.")
            return 0
        print("\n❌ La API no respondió. Se usará el fallback HTML al hacer --rebuild.")
        return 1

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
