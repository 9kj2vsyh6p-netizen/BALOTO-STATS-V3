# Changelog

Todos los cambios notables de **Baloto Stats V3** se documentan aquí.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).

## [3.3.0] - 2026-06-16

### Added
- Batería de **tests automáticos**: 27 de Python (`pytest`) y 19 de JavaScript
  (Node, sin frameworks) en `tests/`.
- Workflow de CI `tests.yml` que ejecuta ambos en cada push y pull request.
- Registro de progreso del scraper por página (`página N/M…`).

### Changed
- Scraper acotado para evitar corridas eternas: tope de páginas por corrida
  (`PAGES_REBUILD`, `PAGES_INCREMENTAL`), *timeout* corto y *fail-fast*.

## [3.2.0] - 2026-06-16

### Changed
- **Origen de datos migrado a las páginas HTML de baloto.com** (`/resultados` y
  `/miloto/resultados`), que se sirven renderizadas y paginadas. Reemplaza a la
  antigua API `api-baloto-prod.baloto.com`.
- El scraper ahora obtiene **datos reales** de Baloto, Revancha y MiLoto.

### Removed
- Adaptador de la API interna `api-baloto-prod` (su DNS dejó de resolver; el
  endpoint fue dado de baja).

### Added
- Parser robusto del HTML con detección automática de paginación.
- Modo `--probe` para verificar la fuente y mostrar lo extraído.
- Marcado de datos de muestra **por juego** (`_meta.sample_games`).

## [3.1.0] - 2026-06-16

### Added
- Páginas de cumplimiento: `juego-responsable.html`, `terminos.html`,
  `privacidad.html`.
- Verificación de mayoría de edad (+18) con `js/agegate.js`.
- Documento `docs/CUMPLIMIENTO.md` con el checklist para monetizar.
- Recursos oficiales de juego responsable de Colombia (Coljuegos, Línea 106).

### Changed
- Pie de página con enlaces legales en toda la app.
- Service worker cachea las nuevas páginas para uso offline.

## [3.0.0] - 2026-06-16

### Added
- Versión inicial de la PWA: dashboard, frecuencias, análisis avanzado y
  generador con 5 motores (incluido Monte Carlo) más modo premium.
- Scraper en Python con validación por juego, merge anti-duplicados, auditoría,
  reintentos y escritura atómica.
- Soporte PWA: `manifest.json`, `sw.js`, iconos, instalable y offline.
- GitHub Actions para actualización automática y despliegue en GitHub Pages.
- Datos de muestra para arranque inmediato.

[3.3.0]: https://github.com/9kj2vsyh6p-netizen/BALOTO-STATS-V3
[3.2.0]: https://github.com/9kj2vsyh6p-netizen/BALOTO-STATS-V3
[3.1.0]: https://github.com/9kj2vsyh6p-netizen/BALOTO-STATS-V3
[3.0.0]: https://github.com/9kj2vsyh6p-netizen/BALOTO-STATS-V3
