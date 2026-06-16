# Fuentes de datos

Este documento explica de dónde salen los resultados y cómo conectar una fuente
real, porque es la parte más frágil de cualquier app de este tipo.

## El problema

No hay una API oficial pública, estable y documentada de Baloto con histórico
profundo. Lo que existe:

- **`baloto.com`** — sitio oficial. Publica resultados pero renderizados con
  JavaScript y paginados; no expone un JSON simple y estable por fecha.
- **Datasets de terceros** (p. ej. Kaggle) — suelen arrancar en 2017 (Baloto
  formato actual) y no se actualizan en tiempo real.
- **Histórico real disponible:** Baloto/Revancha formato actual desde **2017**;
  MiLoto desde **2022**. La afirmación de "desde 2010" del pliego no aplica al
  formato vigente.

Por eso el scraper **no asume una fecha de inicio** y detecta el primer mes con
datos durante el `--rebuild`.

## Adaptadores de fuente

`scripts/scraper.py` aísla la obtención de datos en la clase `Source`. Hay dos
implementaciones:

### 1. `BalotoSiteSource` (por defecto)

Parsea el HTML de `baloto.com` de forma tolerante (fecha + balotas cercanas).
Es *best-effort*: los sitios de lotería cambian su marcado con frecuencia. Si
deja de extraer datos, ajusta el método `parse_html(...)`. Para histórico
profundo hace falta paginar, lo que depende del marcado vigente.

### 2. `JsonEndpointSource` (recomendado si tienes datos propios)

La opción más robusta y mantenible: apunta el scraper a un endpoint JSON que tú
controles (un proxy, un repositorio de datos, un dataset que rehospedas).

```bash
export BALOTO_JSON_URL="https://tu-endpoint.example/api/resultados"
python scripts/scraper.py --rebuild
```

El endpoint recibe `?game=&year=&month=` y debe responder una lista de objetos:

```json
[
  { "fecha": "2026-06-10", "sorteo": 2610, "numeros": [3,5,17,18,27], "superbalota": 7 }
]
```

Acepta también las claves alternativas `date / draw / numbers / superball`.

## Cómo agregar tu propio adaptador

1. Crea una subclase de `Source` con el método
   `fetch_month(self, game, year, month) -> list[Draw]`.
2. Devuelve objetos `Draw(fecha, sorteo, numeros, superbalota)` sin validar
   (el pipeline valida y deduplica por ti).
3. Regístrala en `make_source(...)`.

## Validación y reglas por juego

| Juego    | Números | Rango | Superbalota |
|----------|---------|-------|-------------|
| Baloto   | 5       | 1–43  | 1–16        |
| Revancha | 5       | 1–43  | 1–16        |
| MiLoto   | 5       | 1–39  | —           |

Cualquier registro que no cumpla estas reglas se descarta y aparece en el
reporte de `--audit` con su razón.

## Carga inicial recomendada

```bash
# 1) Configura tu fuente (endpoint JSON propio o ajusta el parser de baloto.com)
# 2) Reconstruye desde el inicio real de cada juego
python scripts/scraper.py --rebuild --game baloto   --since 2017/01
python scripts/scraper.py --rebuild --game revancha --since 2017/01
python scripts/scraper.py --rebuild --game miloto   --since 2022/05
# 3) Verifica
python scripts/scraper.py --audit
```
