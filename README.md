# Baloto Stats V3

PWA de análisis estadístico para **Baloto**, **Baloto Revancha** y **MiLoto**.
Descarga el histórico de resultados, calcula estadísticas avanzadas y genera
líneas con varios modelos. Instalable, funciona offline y se actualiza sola
mediante GitHub Actions + GitHub Pages.

> **Aviso honesto:** la lotería es un proceso aleatorio. Las combinaciones que
> genera la app **no aumentan la probabilidad de ganar**; son una herramienta
> estadística y de entretenimiento. Juega con responsabilidad. +18.

---

## ⚠️ Sobre la fuente de datos (léelo antes de empezar)

El pliego original asumía "una API oficial con histórico desde 2010". En la
práctica:

- **No existe una API oficial pública y documentada** de Baloto con histórico
  profundo. `baloto.com` renderiza los resultados con JavaScript y los pagina.
- El **formato actual** del Baloto (5 números 1–43 + superbalota 1–16) arranca
  en **2017** (el "Nuevo Baloto"). **MiLoto** es de **2022** aprox.
- Por eso el scraper **detecta automáticamente el primer mes con datos** en
  lugar de asumir una fecha de inicio.

El scraper usa un patrón de **adaptadores de fuente** para que puedas conectar
la fuente que prefieras sin tocar el resto del código. Detalles y opciones en
[`docs/FUENTES.md`](docs/FUENTES.md).

El repo incluye **datos de muestra** (`data/resultados.json`) para que la app
funcione de inmediato. Reemplázalos con datos reales ejecutando el scraper.

---

## Estructura

```
BALOTO-STATS-V3/
├── .github/workflows/      actualizar.yml · rebuild.yml · audit.yml
├── data/resultados.json    datos (baloto / revancha / miloto)
├── scripts/
│   ├── scraper.py          descarga + merge anti-duplicados + auditoría
│   ├── seed_sample.py      generador de datos de muestra
│   └── requirements.txt
├── js/                     data, stats, analysis, generators, charts, ui, app
├── css/styles.css
├── icons/                  iconos PWA (192 / 512 / maskable)
├── docs/                   documentación (FUENTES.md)
├── index.html · manifest.json · sw.js · README.md
```

## Probar localmente

La app es estática, pero el Service Worker y `fetch` necesitan un servidor (no
abras `index.html` con `file://`):

```bash
python -m http.server 8000
# abre http://localhost:8000
```

## Datos: scraper

```bash
pip install -r scripts/requirements.txt

python scripts/scraper.py               # actualización incremental (últimos meses)
python scripts/scraper.py --rebuild     # reconstrucción completa del histórico
python scripts/scraper.py --audit       # diagnóstico mes a mes (no escribe)
python scripts/scraper.py --game miloto --rebuild --since 2022/05
```

Formato de cada registro en `data/resultados.json`:

```json
{ "fecha": "2026-06-10", "sorteo": 2610, "numeros": [3,5,17,18,27], "superbalota": 7 }
```

- **MiLoto** no usa superbalota → `"superbalota": null`.
- **Merge anti-duplicados:** clave primaria `fecha + sorteo`; si falta el número
  de sorteo, `fecha + numeros`. Nunca se duplican registros.

### Diagnóstico (`--audit`)

Muestra, por mes: registros de la fuente, aceptados, descartados (con la razón)
y agregados. Útil para detectar huecos o cambios en el marcado de la fuente.

## Publicar en GitHub Pages

1. Sube el repo a GitHub.
2. **Settings → Pages → Build and deployment → Deploy from a branch.**
3. Branch: `main`, carpeta `/ (root)`. Guarda.
4. La app queda en `https://<usuario>.github.io/<repo>/`.

Cada vez que el workflow de actualización haga commit de `data/resultados.json`,
Pages se reconstruye solo.

## Automatización (GitHub Actions)

| Workflow         | Cuándo                                   | Qué hace                                   |
|------------------|------------------------------------------|--------------------------------------------|
| `actualizar.yml` | Diario 00:30 (hora CO) + manual          | Scrape incremental y commit de nuevos datos|
| `rebuild.yml`    | Manual                                   | Reconstrucción completa del histórico      |
| `audit.yml`      | Manual + lunes                           | Diagnóstico; publica reporte como artefacto|

> El workflow necesita permiso de escritura (`contents: write`, ya incluido) para
> commitear los datos. Si usas un endpoint JSON propio, configúralo como
> *repository variable* `BALOTO_JSON_URL` (Settings → Secrets and variables →
> Actions → Variables).

## Funciones de la app

- **Dashboard:** total de sorteos, último resultado, cobertura, calientes/fríos,
  frecuencia histórica y de los últimos 100 / 500.
- **Frecuencias:** ranking con ventanas móviles (25/50/100/200/500/1000), Top
  5/10/20 calientes y fríos, ausencia, mapa de calor y tendencia por ventanas.
- **Análisis:** pares/impares, bajos/altos, décadas, suma, consecutivos,
  parejas (Top 50), tríos (Top 50) y cuartetos (Top 25).
- **Generador:** 5 motores (frecuencia simple, frecuencia ponderada, hot/cold,
  Monte Carlo ≥100.000 simulaciones, híbrido premium) y modo premium con líneas
  Conservadora / Equilibrada / Agresiva.

## Calidad del código

El scraper incluye logging a `scripts/scraper.log`, reintentos con backoff,
timeouts, validación por juego (rango de números y superbalota), escritura
atómica del JSON y modo auditoría. Los módulos JS están separados por
responsabilidad y son independientes del framework.

## Licencia

Uso personal y educativo. Proyecto no oficial, sin relación con el operador del
juego ni con Coljuegos.
