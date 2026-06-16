# -*- coding: utf-8 -*-
"""Tests del scraper de BALOTO STATS V3.

Ejecutar:  pytest -q
Cubren: validación por juego, merge anti-duplicados, parseo del HTML de
baloto.com, fechas en español, paginación y el blindaje del rebuild.
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

# Importar scripts/scraper.py sin ejecutarlo como programa
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import scraper as s  # noqa: E402


# --------------------------------------------------------------------------- #
# Validación
# --------------------------------------------------------------------------- #

def test_validate_baloto_ok():
    d = s.Draw("2026-06-15", 2670, [4, 13, 16, 22, 31], 11)
    s.validate("baloto", d)  # no lanza


def test_validate_miloto_sin_superbalota():
    d = s.Draw("2026-06-15", 554, [11, 16, 28, 33, 38], None)
    s.validate("miloto", d)
    assert d.superbalota is None


@pytest.mark.parametrize("draw,game", [
    (s.Draw("2026-06-15", 1, [4, 13, 16, 22], 11), "baloto"),          # faltan números
    (s.Draw("2026-06-15", 1, [4, 13, 16, 22, 99], 11), "baloto"),      # fuera de rango
    (s.Draw("2026-06-15", 1, [4, 4, 16, 22, 31], 11), "baloto"),       # repetidos
    (s.Draw("2026-06-15", 1, [4, 13, 16, 22, 31], 99), "baloto"),      # superbalota mala
    (s.Draw("fecha-mala", 1, [4, 13, 16, 22, 31], 11), "baloto"),      # fecha inválida
    (s.Draw("2026-06-15", 1, [4, 13, 16, 22, 45], None), "miloto"),    # miloto fuera de rango
])
def test_validate_rechaza(draw, game):
    with pytest.raises(s.ValidationError):
        s.validate(game, draw)


# --------------------------------------------------------------------------- #
# Merge anti-duplicados
# --------------------------------------------------------------------------- #

def test_merge_sin_duplicados():
    rows = []
    nuevos = [
        s.Draw("2026-06-15", 2670, [4, 13, 16, 22, 31], 11),
        s.Draw("2026-06-13", 2669, [13, 18, 26, 28, 29], 10),
    ]
    added, dup = s.merge_game(rows, nuevos)
    assert added == 2 and dup == 0 and len(rows) == 2


def test_merge_duplicado_por_sorteo():
    rows = []
    s.merge_game(rows, [s.Draw("2026-06-15", 2670, [4, 13, 16, 22, 31], 11)])
    added, dup = s.merge_game(rows, [s.Draw("2026-06-15", 2670, [1, 2, 3, 4, 5], 7)])
    assert added == 0 and dup == 1  # mismo (fecha, sorteo) -> duplicado


def test_merge_duplicado_por_numeros_sin_sorteo():
    rows = []
    s.merge_game(rows, [s.Draw("2026-06-15", None, [4, 13, 16, 22, 31], 11)])
    added, dup = s.merge_game(rows, [s.Draw("2026-06-15", None, [31, 22, 16, 13, 4], 11)])
    assert added == 0 and dup == 1  # mismos números aunque en otro orden


def test_merge_ordena_por_fecha():
    rows = []
    s.merge_game(rows, [
        s.Draw("2026-06-15", 2670, [4, 13, 16, 22, 31], 11),
        s.Draw("2026-01-01", 2600, [1, 2, 3, 4, 5], 1),
    ])
    assert [r["fecha"] for r in rows] == ["2026-01-01", "2026-06-15"]


# --------------------------------------------------------------------------- #
# Parseo del HTML de baloto.com
# --------------------------------------------------------------------------- #

BALOTO_HTML = """<html><body><div>Página 1 de 118</div><table><tbody>
<tr><td><img></td><td>15 de Junio de 2026</td><td>04 - 13 - 16 - 22 - 31 - 11</td>
    <td><a href="https://baloto.com/resultados-baloto/2670">Ver</a></td></tr>
<tr><td><img></td><td>15 de Junio de 2026</td><td>18 - 24 - 32 - 37 - 39 - 03</td>
    <td><a href="https://baloto.com/resultados-revancha/2670">Ver</a></td></tr>
<tr><td><img></td><td>13 de Junio de 2026</td><td>13 - 18 - 26 - 28 - 29 - 10</td>
    <td><a href="https://baloto.com/resultados-baloto/2669">Ver</a></td></tr>
</tbody></table></body></html>"""

MILOTO_HTML = """<html><body><div>Página 1 de 56</div><table><tbody>
<tr><td>15 de Junio de 2026</td><td>11 - 16 - 28 - 33 - 38</td>
    <td><a href="https://baloto.com/miloto/resultados-miloto/554/">Ver</a></td></tr>
<tr><td>4 de Junio de 2026</td><td>03 - 07 - 12 - 17 - 36</td>
    <td><a href="https://baloto.com/miloto/resultados-miloto/548/">Ver</a></td></tr>
</tbody></table></body></html>"""


def test_parse_baloto_page():
    out = s.parse_baloto_page(BALOTO_HTML)
    bal = {d.sorteo: d for d in out["baloto"]}
    rev = {d.sorteo: d for d in out["revancha"]}
    assert bal[2670].numeros == [4, 13, 16, 22, 31] and bal[2670].superbalota == 11
    assert bal[2670].fecha == "2026-06-15"
    assert rev[2670].numeros == [18, 24, 32, 37, 39] and rev[2670].superbalota == 3
    assert bal[2669].numeros == [13, 18, 26, 28, 29]


def test_parse_miloto_page():
    out = {d.sorteo: d for d in s.parse_miloto_page(MILOTO_HTML)}
    assert out[554].numeros == [11, 16, 28, 33, 38] and out[554].superbalota is None
    assert out[554].fecha == "2026-06-15"
    assert out[548].numeros == [3, 7, 12, 17, 36]


def test_parsed_draws_son_validos():
    out = s.parse_baloto_page(BALOTO_HTML)
    for d in out["baloto"]:
        s.validate("baloto", d)
    for d in out["revancha"]:
        s.validate("revancha", d)
    for d in s.parse_miloto_page(MILOTO_HTML):
        s.validate("miloto", d)


# --------------------------------------------------------------------------- #
# Utilidades de parseo
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("texto,esperado", [
    ("15 de Junio de 2026", "2026-06-15"),
    ("4 de Junio de 2026", "2026-06-04"),
    ("29 de Mayo de 2026", "2026-05-29"),
    ("1 de Enero de 2025", "2025-01-01"),
    ("texto sin fecha", None),
    ("30 de Febrero de 2026", None),  # fecha imposible
])
def test_parse_spanish_date(texto, esperado):
    assert s._parse_spanish_date(texto) == esperado


@pytest.mark.parametrize("html,esperado", [
    ("Página 1 de 118", 118),
    ("Página 3 de 56", 56),
    ("sin paginación", 1),
])
def test_max_pages(html, esperado):
    assert s._max_pages(html) == esperado


# --------------------------------------------------------------------------- #
# Cobertura y blindaje del rebuild
# --------------------------------------------------------------------------- #

def test_coverage_summary():
    store = {
        "baloto": [{"fecha": "2025-01-01", "sorteo": 1, "numeros": [1, 2, 3, 4, 5], "superbalota": 1},
                   {"fecha": "2026-06-15", "sorteo": 2, "numeros": [6, 7, 8, 9, 10], "superbalota": 2}],
        "revancha": [], "miloto": [],
    }
    cov = s.coverage_summary(store)
    assert cov["baloto"] == {"desde": "2025-01-01", "hasta": "2026-06-15", "total": 2}
    assert cov["revancha"]["total"] == 0


class _FakeSource(s.Source):
    """Fuente simulada para probar el proceso sin red."""
    def __init__(self, session, data=None):
        super().__init__(session)
        self.data = data or {}

    def supports(self, game):
        return True

    def fetch_month(self, game, year, month):
        return self.data.get((game, year, month), [])


def _prep_store(tmp_path, monkeypatch):
    data_file = tmp_path / "resultados.json"
    data_file.write_text(json.dumps({
        "_meta": {"sample_games": ["baloto", "revancha", "miloto"]},
        "baloto": [{"fecha": "2020-01-01", "sorteo": 1, "numeros": [1, 2, 3, 4, 5], "superbalota": 1}],
        "revancha": [], "miloto": [],
    }))
    monkeypatch.setattr(s, "DATA_FILE", data_file)
    monkeypatch.setattr(s, "build_session", lambda: None)
    return data_file


def test_rebuild_carga_datos_reales(tmp_path, monkeypatch):
    data_file = _prep_store(tmp_path, monkeypatch)
    real = {("baloto", 2026, 6): [s.Draw("2026-06-15", 2670, [4, 13, 16, 22, 31], 11)]}
    monkeypatch.setattr(s, "make_source", lambda sess, page_limit=None: _FakeSource(sess, real))
    s.process(["baloto"], (2026, 6), (2026, 6), audit=False, write=True, reset=True)
    d = json.loads(data_file.read_text())
    assert d["baloto"][-1]["sorteo"] == 2670
    assert "baloto" not in d["_meta"]["sample_games"]  # ya es real
    assert all(r["sorteo"] != 1 for r in d["baloto"])  # muestra reemplazada


def test_rebuild_blindaje_conserva_si_no_hay_datos(tmp_path, monkeypatch):
    data_file = _prep_store(tmp_path, monkeypatch)
    monkeypatch.setattr(s, "make_source", lambda sess, page_limit=None: _FakeSource(sess, {}))
    s.process(["baloto"], (2026, 6), (2026, 6), audit=False, write=True, reset=True)
    d = json.loads(data_file.read_text())
    assert len(d["baloto"]) == 1  # NO se borró la muestra
    assert "baloto" in d["_meta"]["sample_games"]
