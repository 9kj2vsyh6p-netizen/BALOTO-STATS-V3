#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Genera un dataset de MUESTRA para BALOTO STATS V3.

Sirve únicamente para que la PWA funcione y se vea de inmediato sin haber
ejecutado todavía el scraper contra la fuente real. Los sorteos son
sintéticos (aleatorios reproducibles) EXCEPTO los más recientes, que se
siembran con resultados reales verificados.

Reemplaza estos datos ejecutando:  python scripts/scraper.py --rebuild
"""

import json
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "resultados.json"

random.seed(43)  # reproducible

# Sorteos reales recientes (verificados) usados como ancla de credibilidad.
REAL = {
    "baloto": [
        {"fecha": "2026-06-10", "sorteo": 2610, "numeros": [3, 5, 17, 18, 27], "superbalota": 7},
    ],
    "revancha": [
        {"fecha": "2026-06-10", "sorteo": 2610, "numeros": [7, 14, 22, 35, 41], "superbalota": 6},
    ],
    "miloto": [
        {"fecha": "2026-06-04", "sorteo": 548, "numeros": [4, 11, 23, 30, 37], "superbalota": None},
    ],
}

# Días de sorteo por juego (0=lunes ... 6=domingo)
DRAW_DAYS = {
    "baloto":   {0, 2, 5},        # lunes, miércoles, sábado
    "revancha": {0, 2, 5},
    "miloto":   {0, 1, 3, 4},     # lunes, martes, jueves, viernes
}

RULES = {
    "baloto":   {"count": 5, "max": 43, "sb": 16, "start": date(2017, 6, 1)},
    "revancha": {"count": 5, "max": 43, "sb": 16, "start": date(2017, 6, 1)},
    "miloto":   {"count": 5, "max": 39, "sb": None, "start": date(2022, 5, 1)},
}


def gen(game: str, until: date) -> list[dict]:
    r = RULES[game]
    rows, d, sorteo = [], r["start"], 1000 if game != "miloto" else 1
    while d <= until:
        if d.weekday() in DRAW_DAYS[game]:
            nums = sorted(random.sample(range(1, r["max"] + 1), r["count"]))
            sb = random.randint(1, r["sb"]) if r["sb"] else None
            rows.append({"fecha": d.isoformat(), "sorteo": sorteo,
                         "numeros": nums, "superbalota": sb})
            sorteo += 1
        d += timedelta(days=1)
    return rows


def main():
    until = date(2026, 6, 9)
    store = {"_meta": {"sample_games": ["baloto", "revancha", "miloto"],
                       "nota": "Datos de muestra. Ejecuta scraper.py --rebuild para datos reales."}}
    for game in ("baloto", "revancha", "miloto"):
        rows = gen(game, until)
        # Anexa los sorteos reales (sin duplicar fecha)
        existing = {x["fecha"] for x in rows}
        for real in REAL[game]:
            if real["fecha"] not in existing:
                rows.append(real)
        rows.sort(key=lambda x: (x["fecha"], x["sorteo"]))
        store[game] = rows

    store["_meta"]["cobertura"] = {
        g: {"desde": store[g][0]["fecha"], "hasta": store[g][-1]["fecha"], "total": len(store[g])}
        for g in ("baloto", "revancha", "miloto")
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, separators=(",", ":"))

    for g in ("baloto", "revancha", "miloto"):
        c = store["_meta"]["cobertura"][g]
        print(f"{g:9} {c['total']:5} sorteos  {c['desde']} -> {c['hasta']}")
    print(f"\nEscrito: {OUT}  ({OUT.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
