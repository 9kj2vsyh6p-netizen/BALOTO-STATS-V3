#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BALOTO STATS V3 — Scraper de resultados históricos.

Origen de datos (2026): páginas oficiales de baloto.com, que entregan los
resultados en HTML renderizado por el servidor y paginado:

  * Baloto + Revancha:  https://baloto.com/resultados?page=N
  * MiLoto:             https://baloto.com/miloto/resultados/?page=N

(La antigua API api-baloto-prod.baloto.com fue dada de baja: su DNS ya no
resuelve. Por eso ahora se lee el HTML servido, que sí está vivo.)

Compatibilidad: escribe data/resultados.json con el MISMO formato de siempre.

Modos:
  python scraper.py                 # actualización incremental (primeras páginas)
  python scraper.py --rebuild       # reconstrucción completa (todas las páginas)
  python scraper.py --audit         # diagnóstico mes a mes (no escribe)
  python scraper.py --probe         # PRUEBA: lee la página 1 y muestra lo extraído
  python scraper.py --game miloto   # limita a un juego
  python scraper.py --since 2017/01 # punto de partida del rebuild (filtra por fecha)
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

REQUEST_TIMEOUT = 12
RETRY_TOTAL = 1
RETRY_BACKOFF = 0.6
THROTTLE_SECONDS = 0.6
PAGE_CAP = 250  # tope de seguridad de páginas a recorrer
PAGES_REBUILD = 25   # páginas por juego en --rebuild (~125 sorteos baloto, ~250 miloto)
PAGES_INCREMENTAL = 4
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

URL_BALOTO = "https://baloto.com/resultados?page={}"
URL_MILOTO = "https://baloto.com/miloto/resultados/?page={}"

MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
         "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
         "noviembre": 11, "diciembre": 12}


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

def setup_logging(verbose=True, debug=False):
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


def validate(game, draw):
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

def build_session():
    session = requests.Session()
    retry = Retry(total=RETRY_TOTAL, connect=RETRY_TOTAL, read=RETRY_TOTAL,
                  backoff_factor=RETRY_BACKOFF, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset(["GET"]), raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-CO,es;q=0.9",
        "Referer": "https://baloto.com/",
    })
    return session


# --------------------------------------------------------------------------- #
# Parseo del HTML de baloto.com
# --------------------------------------------------------------------------- #

def _parse_spanish_date(s):
    m = re.search(r"(\d{1,2})\s+de\s+([A-Za-zÁÉÍÓÚáéíóúñ]+)\s+de\s+(\d{4})", s or "")
    if not m:
        return None
    mes = MESES.get(m.group(2).lower())
    if not mes:
        return None
    try:
        return date(int(m.group(3)), mes, int(m.group(1))).isoformat()
    except ValueError:
        return None


def _row_text(a):
    node = a.find_parent("tr") or a.parent
    return node.get_text(" ", strip=True) if node else ""


def parse_baloto_page(html):
    """Extrae baloto y revancha de una página /resultados. -> {'baloto':[],'revancha':[]}"""
    out = {"baloto": [], "revancha": []}
    if not _HAS_BS4:
        return out
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=re.compile(r"/resultados-(baloto|revancha)/(\d+)")):
        mm = re.search(r"/resultados-(baloto|revancha)/(\d+)", a["href"])
        game, sorteo = mm.group(1), int(mm.group(2))
        row = _row_text(a)
        fecha = _parse_spanish_date(row)
        run = re.search(r"(\d{1,2}(?:\s*-\s*\d{1,2}){4,5})", row)
        if not fecha or not run:
            continue
        nums = [int(x) for x in re.findall(r"\d{1,2}", run.group(1))]
        if len(nums) < 5:
            continue
        out[game].append(Draw(fecha, sorteo, nums[:5], nums[5] if len(nums) >= 6 else None))
    return out


def parse_miloto_page(html):
    """Extrae miloto de una página /miloto/resultados. -> [Draw]"""
    out = []
    if not _HAS_BS4:
        return out
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=re.compile(r"/resultados-miloto/(\d+)")):
        sorteo = int(re.search(r"/resultados-miloto/(\d+)", a["href"]).group(1))
        row = _row_text(a)
        fecha = _parse_spanish_date(row)
        run = re.search(r"(\d{1,2}(?:\s*-\s*\d{1,2}){4})(?!\s*-\s*\d)", row)
        if not fecha or not run:
            continue
        nums = [int(x) for x in re.findall(r"\d{1,2}", run.group(1))][:5]
        out.append(Draw(fecha, sorteo, nums, None))
    return out


def _max_pages(html):
    m = re.search(r"P[aá]gina\s+\d+\s+de\s+(\d+)", html or "")
    return int(m.group(1)) if m else 1


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


class HtmlListingSource(Source):
    """Lee las páginas de resultados de baloto.com (HTML servido, paginado)."""
    name = "baloto.com-listing"

    def __init__(self, session, page_limit=None):
        super().__init__(session)
        self.page_limit = page_limit          # None = todas las páginas
        self._idx = {}                         # game -> {(y,m): [Draw]}
        self._raw_baloto = None                # cache de baloto+revancha

    def supports(self, game):
        return game in GAMES

    def _get(self, url):
        try:
            r = self.session.get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            log.warning("GET %s -> fallo de red: %s", url, exc)
            return None
        time.sleep(THROTTLE_SECONDS)
        if r.status_code != 200:
            log.warning("GET %s -> HTTP %s", url, r.status_code)
            return None
        log.debug("GET %s -> HTTP 200  %d bytes", url, len(r.text or ""))
        return r.text

    def _crawl(self, url_tmpl, parse_fn, label):
        """Recorre todas las páginas y acumula resultados."""
        first = self._get(url_tmpl.format(1))
        if not first:
            log.warning("%s: no se pudo leer la página 1", label)
            return parse_fn("")  # vacío del tipo correcto
        total = _max_pages(first)
        limit = total if self.page_limit is None else min(total, self.page_limit)
        log.info("%s: %d páginas detectadas, recorriendo %d", label, total, limit)
        acc = parse_fn(first)
        for p in range(2, min(limit, PAGE_CAP) + 1):
            if p % 5 == 0:
                log.info("%s: página %d/%d…", label, p, limit)
            html = self._get(url_tmpl.format(p))
            if not html:
                continue
            part = parse_fn(html)
            if isinstance(acc, dict):
                for k in acc:
                    acc[k].extend(part.get(k, []))
            else:
                acc.extend(part)
        return acc

    def _index(self, game, draws):
        bucket = {}
        for d in draws:
            try:
                y, m = int(d.fecha[:4]), int(d.fecha[5:7])
            except (ValueError, TypeError):
                continue
            bucket.setdefault((y, m), []).append(d)
        self._idx[game] = bucket
        log.info("%s: %d sorteos indexados", game, sum(len(v) for v in bucket.values()))

    def _ensure(self, game):
        if game in self._idx:
            return
        if game in ("baloto", "revancha"):
            if self._raw_baloto is None:
                self._raw_baloto = self._crawl(URL_BALOTO, parse_baloto_page, "Baloto/Revancha")
            self._index("baloto", self._raw_baloto.get("baloto", []))
            self._index("revancha", self._raw_baloto.get("revancha", []))
        else:
            draws = self._crawl(URL_MILOTO, parse_miloto_page, "MiLoto")
            self._index("miloto", draws)

    def fetch_month(self, game, year, month):
        if not self.supports(game):
            return []
        self._ensure(game)
        return self._idx.get(game, {}).get((year, month), [])

    def probe(self):
        """Lee solo la página 1 de Baloto y muestra lo extraído."""
        log.info("PROBE -> GET %s", URL_BALOTO.format(1))
        html = self._get(URL_BALOTO.format(1))
        if not html:
            log.error("PROBE FALLIDO: la página no respondió.")
            return False
        total = _max_pages(html)
        data = parse_baloto_page(html)
        ml_html = self._get(URL_MILOTO.format(1))
        ml = parse_miloto_page(ml_html) if ml_html else []
        ml_total = _max_pages(ml_html) if ml_html else 0
        print("\n" + "=" * 60)
        print("  PRUEBA DE LECTURA — baloto.com")
        print("=" * 60)
        print(f"Baloto/Revancha: {total} páginas (~{total*5} sorteos)")
        print(f"  Baloto pág.1 : {len(data['baloto'])} sorteos")
        for d in data["baloto"][:3]:
            print(f"     {d.fecha}  #{d.sorteo}  {d.numeros}  sb {d.superbalota}")
        print(f"  Revancha pág.1: {len(data['revancha'])} sorteos")
        for d in data["revancha"][:2]:
            print(f"     {d.fecha}  #{d.sorteo}  {d.numeros}  sb {d.superbalota}")
        print(f"MiLoto: {ml_total} páginas (~{ml_total*10} sorteos)")
        for d in ml[:3]:
            print(f"     {d.fecha}  #{d.sorteo}  {d.numeros}")
        print("=" * 60)
        ok = bool(data["baloto"] or data["revancha"])
        log.info("PROBE %s", "OK ✅" if ok else "sin datos ❌")
        return ok


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
        rows = payload if isinstance(payload, list) else payload.get("data", payload.get("results", []))
        out = []
        for r in rows:
            out.append(Draw(str(r.get("fecha") or r.get("date"))[:10],
                            _to_int(r.get("sorteo") or r.get("draw")),
                            [int(x) for x in (r.get("numeros") or r.get("numbers") or [])],
                            _to_int(r.get("superbalota") or r.get("sb"))))
        return out


def make_source(session, page_limit=None):
    json_url = os.environ.get("BALOTO_JSON_URL", "").strip()
    if json_url:
        log.info("Fuente: endpoint JSON propio (%s)", json_url)
        return JsonEndpointSource(session, json_url)
    log.info("Fuente: baloto.com (HTML servido, paginado)")
    return HtmlListingSource(session, page_limit=page_limit)


# --------------------------------------------------------------------------- #
# Almacenamiento y merge
# --------------------------------------------------------------------------- #

def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


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
    # incremental = pocas páginas; rebuild = todas
    source = make_source(session, page_limit=PAGES_REBUILD if reset else PAGES_INCREMENTAL)
    store = load_store()
    report = {g: [] for g in games}
    made_real = []
    total_added = 0

    for game in games:
        if not source.supports(game):
            log.info("=== %s === (no soportado; se conserva)", game.upper())
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
                    log.warning("%s: la fuente no devolvió datos; se conservan los previos", game)
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
            print(f"\n{e['mes']}  Fuente:{e['api']}  Acept:{e['aceptados']}  "
                  f"Desc:{e['descartados']}  Agreg:{e['agregados']}")
            for r, c in e["razones"].items():
                print(f"     - {r}: {c}")
    print("\n" + "-" * 56)
    print("  COBERTURA DETECTADA")
    print("-" * 56)
    for g, c in result["cobertura"].items():
        if c["total"]:
            print(f"  {g.capitalize():9} desde {c['desde']}  hasta {c['hasta']}  total {c['total']}")
        else:
            print(f"  {g.capitalize():9} sin datos")
    print()


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
    parser.add_argument("--audit", action="store_true", help="Diagnóstico (no escribe)")
    parser.add_argument("--probe", action="store_true", help="Prueba de lectura (página 1)")
    parser.add_argument("--game", choices=list(GAMES) + ["all"], default="all")
    parser.add_argument("--since", default="", help="Inicio del rebuild YYYY/MM")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(verbose=not args.quiet, debug=args.debug)

    if args.probe:
        session = build_session()
        ok = HtmlListingSource(session, page_limit=1).probe()
        print("\n✅ baloto.com respondió y se leyeron resultados." if ok
              else "\n❌ No se pudieron leer resultados (revisa el log).")
        return 0 if ok else 1

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
