#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BALOTO STATS V3 — Scraper de resultados históricos.

Descarga resultados de Baloto, Baloto Revancha y MiLoto, los normaliza y los
guarda en data/resultados.json aplicando un merge inteligente anti-duplicados.

Modos de uso
------------
    python scraper.py                 # Actualización incremental (últimos meses)
    python scraper.py --rebuild       # Reconstrucción completa del histórico
    python scraper.py --audit         # Diagnóstico mes a mes (no escribe datos)
    python scraper.py --game miloto   # Limita a un juego concreto
    python scraper.py --since 2017/01 # Punto de partida para el rebuild

Diseño
------
La obtención de datos está aislada en "adaptadores de fuente" (clase Source).
Esto permite cambiar de fuente sin tocar el resto del programa. Se incluye:

  * BalotoSiteSource  -> parsea las páginas oficiales de baloto.com (best-effort).
  * JsonEndpointSource -> apunta a un endpoint JSON propio vía variable de entorno
                          BALOTO_JSON_URL (formato {fecha,sorteo,numeros,superbalota}).

IMPORTANTE: los sitios de lotería cambian su HTML con frecuencia. Si el parseo
deja de funcionar, ajusta el método `parse(...)` del adaptador correspondiente.
No existe una API oficial pública documentada con histórico "desde 2010"; el
formato actual del Baloto (1-43 + superbalota 1-16) arranca en 2017. El scraper
DETECTA automáticamente el primer mes con datos en lugar de asumir una fecha.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
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

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:  # pragma: no cover
    _HAS_BS4 = False


# --------------------------------------------------------------------------- #
# Configuración global
# --------------------------------------------------------------------------- #

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "resultados.json"
LOG_FILE = ROOT / "scripts" / "scraper.log"

GAMES = ("baloto", "revancha", "miloto")

# Reglas de validación por juego: (cantidad_numeros, min, max, tiene_superbalota, sb_min, sb_max)
GAME_RULES = {
    "baloto":   {"count": 5, "min": 1, "max": 43, "superbalota": True,  "sb_min": 1, "sb_max": 16},
    "revancha": {"count": 5, "min": 1, "max": 43, "superbalota": True,  "sb_min": 1, "sb_max": 16},
    "miloto":   {"count": 5, "min": 1, "max": 39, "superbalota": False, "sb_min": 0, "sb_max": 0},
}

REQUEST_TIMEOUT = 20          # segundos
RETRY_TOTAL = 5
RETRY_BACKOFF = 1.5           # backoff exponencial entre reintentos
THROTTLE_SECONDS = 0.4        # pausa cortés entre peticiones
USER_AGENT = (
    "BalotoStatsV3/1.0 (+https://github.com/) statistical-research; "
    "respeta robots y juego responsable"
)


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
    """Un sorteo normalizado."""
    fecha: str               # YYYY-MM-DD
    sorteo: Optional[int]    # número de sorteo (puede faltar en algunas fuentes)
    numeros: list[int]
    superbalota: Optional[int]

    def to_dict(self) -> dict:
        return {
            "fecha": self.fecha,
            "sorteo": self.sorteo,
            "numeros": self.numeros,
            "superbalota": self.superbalota,
        }

    def key_primary(self) -> Optional[tuple]:
        if self.sorteo is not None:
            return (self.fecha, int(self.sorteo))
        return None

    def key_fallback(self) -> tuple:
        return (self.fecha, tuple(sorted(self.numeros)))


class ValidationError(Exception):
    pass


def validate(game: str, draw: Draw) -> None:
    """Lanza ValidationError con una razón legible si el sorteo es inválido."""
    rules = GAME_RULES[game]

    # Fecha
    try:
        datetime.strptime(draw.fecha, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise ValidationError(f"fecha invalida: {draw.fecha!r}")

    # Números
    nums = draw.numeros
    if not isinstance(nums, list) or len(nums) != rules["count"]:
        raise ValidationError(f"se esperaban {rules['count']} numeros, hay {len(nums) if nums else 0}")
    if len(set(nums)) != len(nums):
        raise ValidationError("numeros repetidos")
    for n in nums:
        if not isinstance(n, int) or not (rules["min"] <= n <= rules["max"]):
            raise ValidationError(f"numero fuera de rango [{rules['min']},{rules['max']}]: {n}")

    # Superbalota
    if rules["superbalota"]:
        sb = draw.superbalota
        if sb is None or not (rules["sb_min"] <= sb <= rules["sb_max"]):
            raise ValidationError(f"superbalota fuera de rango [{rules['sb_min']},{rules['sb_max']}]: {sb}")
    else:
        # MiLoto no usa superbalota
        draw.superbalota = None


# --------------------------------------------------------------------------- #
# Cliente HTTP con reintentos
# --------------------------------------------------------------------------- #

def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=RETRY_TOTAL,
        connect=RETRY_TOTAL,
        read=RETRY_TOTAL,
        backoff_factor=RETRY_BACKOFF,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "es-CO,es;q=0.9"})
    return session


# --------------------------------------------------------------------------- #
# Adaptadores de fuente
# --------------------------------------------------------------------------- #

class Source:
    """Interfaz de una fuente de datos."""
    name = "base"

    def __init__(self, session: requests.Session):
        self.session = session

    def fetch_month(self, game: str, year: int, month: int) -> list[Draw]:
        """Devuelve los sorteos crudos (sin validar) de un (juego, año, mes)."""
        raise NotImplementedError


class JsonEndpointSource(Source):
    """
    Fuente genérica: un endpoint JSON propio que devuelve una lista de objetos
    {fecha, sorteo, numeros, superbalota}. Se configura con BALOTO_JSON_URL.

    El endpoint recibe parámetros ?game=&year=&month= y debe responder JSON.
    Útil si mantienes tu propio proxy/cache de resultados.
    """
    name = "json-endpoint"

    def __init__(self, session: requests.Session, base_url: str):
        super().__init__(session)
        self.base_url = base_url.rstrip("?&")

    def fetch_month(self, game: str, year: int, month: int) -> list[Draw]:
        sep = "&" if "?" in self.base_url else "?"
        url = f"{self.base_url}{sep}game={game}&year={year}&month={month:02d}"
        log.debug("GET %s", url)
        resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
        time.sleep(THROTTLE_SECONDS)
        if resp.status_code != 200:
            log.warning("HTTP %s en %s", resp.status_code, url)
            return []
        try:
            payload = resp.json()
        except ValueError:
            log.warning("Respuesta no-JSON en %s", url)
            return []
        rows = payload if isinstance(payload, list) else payload.get("data", payload.get("results", []))
        draws: list[Draw] = []
        for r in rows:
            draws.append(Draw(
                fecha=str(r.get("fecha") or r.get("date"))[:10],
                sorteo=_to_int(r.get("sorteo") or r.get("draw") or r.get("numero")),
                numeros=[int(x) for x in (r.get("numeros") or r.get("numbers") or [])],
                superbalota=_to_int(r.get("superbalota") or r.get("superball") or r.get("sb")),
            ))
        return draws


class BalotoSiteSource(Source):
    """
    Adaptador best-effort para las páginas de resultados de baloto.com.

    ADVERTENCIA: el sitio oficial renderiza con JavaScript y cambia su marcado
    con frecuencia. Este parser cubre el patrón "fecha + 5 números + superbalota"
    sobre el HTML servido. Si deja de extraer datos, revisa `parse_html`.
    Para un histórico estable considera mantener tu propio dataset o un endpoint
    JSON (ver JsonEndpointSource).
    """
    name = "baloto.com"

    URLS = {
        "baloto":   "https://baloto.com/resultados",
        "revancha": "https://baloto.com/resultados",
        "miloto":   "https://baloto.com/miloto/resultados",
    }

    def fetch_month(self, game: str, year: int, month: int) -> list[Draw]:
        # El sitio no expone filtro por mes vía URL simple; se descarga el
        # listado disponible y luego se filtra por (año, mes). Para histórico
        # profundo es necesario paginar, lo que depende del marcado vigente.
        url = self.URLS[game]
        log.debug("GET %s (%s %04d/%02d)", url, game, year, month)
        try:
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            log.warning("Fallo de red en %s: %s", url, exc)
            return []
        time.sleep(THROTTLE_SECONDS)
        if resp.status_code != 200:
            log.warning("HTTP %s en %s", resp.status_code, url)
            return []
        draws = self.parse_html(resp.text, game)
        return [d for d in draws if _in_month(d.fecha, year, month)]

    @staticmethod
    def parse_html(html: str, game: str) -> list[Draw]:
        """
        Extrae sorteos del HTML. Estrategia tolerante: busca fechas y secuencias
        de balotas cercanas. Ajustar selectores según el marcado vigente.
        """
        draws: list[Draw] = []
        if not _HAS_BS4:
            log.warning("BeautifulSoup no instalado; parseo HTML deshabilitado")
            return draws
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)

        # Patrón muy general: una fecha dd/mm/yyyy seguida (en algún punto) por
        # balotas. Como el marcado real varía, este bloque es un punto de partida.
        date_pat = re.compile(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})")
        for m in date_pat.finditer(text):
            d, mo, y = (int(g) for g in m.groups())
            try:
                fecha = date(y, mo, d).isoformat()
            except ValueError:
                continue
            # Ventana de texto posterior para capturar balotas
            window = text[m.end():m.end() + 120]
            nums = [int(x) for x in re.findall(r"\b(\d{1,2})\b", window)]
            rules = GAME_RULES[game]
            picks = [n for n in nums if rules["min"] <= n <= rules["max"]][: rules["count"]]
            if len(picks) == rules["count"]:
                sb = None
                if rules["superbalota"]:
                    tail = [n for n in nums[rules["count"]:] if rules["sb_min"] <= n <= rules["sb_max"]]
                    sb = tail[0] if tail else None
                draws.append(Draw(fecha=fecha, sorteo=None, numeros=picks, superbalota=sb))
        return draws


def make_source(session: requests.Session) -> Source:
    """Elige la fuente según el entorno."""
    json_url = os.environ.get("BALOTO_JSON_URL", "").strip()
    if json_url:
        log.info("Fuente: endpoint JSON (%s)", json_url)
        return JsonEndpointSource(session, json_url)
    log.info("Fuente: baloto.com (best-effort HTML)")
    return BalotoSiteSource(session)


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
    return store


def save_store(store: dict) -> None:
    store["_meta"]["actualizado"] = datetime.now().isoformat(timespec="seconds")
    store["_meta"]["cobertura"] = coverage_summary(store)
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(DATA_FILE)  # escritura atómica
    log.info("Guardado %s", DATA_FILE)


def build_index(rows: list[dict]) -> tuple[set, set]:
    primary, fallback = set(), set()
    for r in rows:
        if r.get("sorteo") is not None:
            primary.add((r["fecha"], int(r["sorteo"])))
        fallback.add((r["fecha"], tuple(sorted(r["numeros"]))))
    return primary, fallback


def merge_game(store_rows: list[dict], new_draws: list[Draw]) -> tuple[int, int]:
    """
    Inserta solo sorteos no presentes. Clave primaria: (fecha, sorteo).
    Si no hay sorteo: (fecha, numeros). Devuelve (agregados, duplicados).
    """
    primary, fallback = build_index(store_rows)
    added = dup = 0
    for d in new_draws:
        kp = d.key_primary()
        kf = d.key_fallback()
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


def coverage_summary(store: dict) -> dict:
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

def month_range(start: tuple[int, int], end: tuple[int, int]) -> Iterable[tuple[int, int]]:
    (sy, sm), (ey, em) = start, end
    y, m = sy, sm
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m > 12:
            m, y = 1, y + 1


def process(games: list[str], start: tuple[int, int], end: tuple[int, int],
            audit: bool, write: bool) -> dict:
    session = build_session()
    source = make_source(session)
    store = load_store()
    report = {g: [] for g in games}
    total_added = 0

    for game in games:
        log.info("=== %s ===", game.upper())
        for (y, m) in month_range(start, end):
            try:
                raw = source.fetch_month(game, y, m)
            except Exception as exc:  # red u otros; seguimos con el resto
                log.error("Error en %s %04d/%02d: %s", game, y, m, exc)
                raw = []

            accepted: list[Draw] = []
            discarded = 0
            reasons: dict[str, int] = {}
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

            entry = {
                "mes": f"{y:04d}/{m:02d}", "api": len(raw),
                "aceptados": len(accepted), "descartados": discarded,
                "razones": reasons, "agregados": added,
            }
            report[game].append(entry)
            if raw or audit:
                log.info("%s %04d/%02d  API:%d  Acept:%d  Desc:%d  Agreg:%d",
                         game, y, m, len(raw), len(accepted), discarded, added)

    if not audit and write:
        save_store(store)
        log.info("Total agregados en esta corrida: %d", total_added)

    return {"report": report, "cobertura": coverage_summary(store)}


# --------------------------------------------------------------------------- #
# Auditoría legible
# --------------------------------------------------------------------------- #

def print_audit(result: dict) -> None:
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
            if e["razones"]:
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

def _to_int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _in_month(fecha: str, year: int, month: int) -> bool:
    try:
        dt = datetime.strptime(fecha, "%Y-%m-%d")
    except ValueError:
        return False
    return dt.year == year and dt.month == month


def parse_yyyymm(s: str, default: tuple[int, int]) -> tuple[int, int]:
    if not s:
        return default
    m = re.match(r"(\d{4})[/\-](\d{1,2})", s)
    if not m:
        raise SystemExit(f"Formato invalido (use YYYY/MM): {s!r}")
    return int(m.group(1)), int(m.group(2))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scraper de resultados Baloto/Revancha/MiLoto")
    parser.add_argument("--rebuild", action="store_true", help="Reconstrucción completa del histórico")
    parser.add_argument("--audit", action="store_true", help="Diagnóstico mes a mes (no escribe datos)")
    parser.add_argument("--game", choices=list(GAMES) + ["all"], default="all", help="Juego a procesar")
    parser.add_argument("--since", default="", help="Inicio del rebuild en formato YYYY/MM (ej: 2017/01)")
    parser.add_argument("--quiet", action="store_true", help="Menos salida en consola")
    args = parser.parse_args(argv)

    setup_logging(verbose=not args.quiet)

    today = date.today()
    end = (today.year, today.month)

    if args.rebuild or args.audit:
        # Punto de partida razonable por juego; se afina con --since.
        # Baloto/Revancha: formato actual desde 2017. MiLoto: desde 2022.
        default_start = parse_yyyymm(args.since, (2017, 1))
    else:
        # Incremental: solo los últimos ~2 meses
        ym = end[0] * 12 + (end[1] - 1) - 2
        default_start = (ym // 12, ym % 12 + 1)

    games = list(GAMES) if args.game == "all" else [args.game]

    log.info("Modo: %s | Juegos: %s | Rango: %04d/%02d -> %04d/%02d",
             "audit" if args.audit else ("rebuild" if args.rebuild else "incremental"),
             ",".join(games), *default_start, *end)

    result = process(games, default_start, end, audit=args.audit, write=not args.audit)

    if args.audit:
        print_audit(result)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
