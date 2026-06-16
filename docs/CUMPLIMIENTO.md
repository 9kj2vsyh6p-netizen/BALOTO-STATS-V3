# Checklist de cumplimiento y monetización

Guía práctica para dejar Baloto Stats V3 lista para monetizar sin cruzar las
líneas de Coljuegos, Google Play y Google AdSense. **No es asesoría legal;**
valida los puntos sensibles con un abogado antes de publicar.

> Principio rector: te posicionas como **información y estadística**, no como
> operador ni promotor de juego. Todo lo de abajo protege ese encuadre.

---

## A. Posicionamiento (lo que define todo)

- [ ] El sitio se describe como herramienta **informativa y estadística**, nunca
      como forma de "ganar" o "predecir".
- [ ] Ningún texto promete mejorar la probabilidad de ganar, aciertos o premios.
- [ ] No se venden jugadas ni se reciben apuestas ni se intermedian pagos de juego.
- [ ] No hay enlaces de "compra tu tiquete aquí" como función central.
- [ ] El generador se presenta como entretenimiento estadístico (ya rotulado así
      en la app y en Términos).

## B. Activos legales (incluidos en el repo — personalízalos)

- [ ] `juego-responsable.html` — publicada y enlazada en el footer. ✅ incluida
- [ ] `terminos.html` — reemplazar `[NOMBRE]`, `[DOMINIO]`, `[EMAIL]`, `[FECHA]`. ✅ incluida
- [ ] `privacidad.html` — reemplazar campos; **obligatoria para AdSense**. ✅ incluida
- [ ] Age-gate +18 (`js/agegate.js`) — activo al abrir la app. ✅ incluida
- [ ] Disclaimers visibles: "no oficial", "+18", "juega con responsabilidad". ✅ incluidos
- [ ] Revisión legal final de Términos y Privacidad.

## C. Coljuegos (Colombia)

- [ ] Confirmar que **no** operas juego (no vender, no apostar, no pagar premios) →
      si se cumple, no requieres concesión.
- [ ] Mantener el aviso de que la app no está afiliada a Coljuegos ni al operador.
- [ ] Si en el futuro te alías con un operador o cobras ligado a apuestas, **detente
      y consulta**: ahí sí entran licencias/autorizaciones.
- [ ] Enlazar recursos oficiales de juego responsable (Toma el Control, Línea 106). ✅

## D. Google AdSense (vía web — el camino recomendado)

- [ ] Tener la PWA publicada con contenido propio y útil (resultados + estadísticas).
- [ ] Política de privacidad con sección de cookies/AdSense visible. ✅ plantilla incluida
- [ ] No enlazar a servicios de juego propios ni a operadores sin licencia
      (regla de "contenido que promueve juego").
- [ ] Banner de consentimiento de cookies para visitantes de la UE/Reino Unido
      (usa Google Funding Choices / CMP certificado).
- [ ] Solicitar AdSense **estándar (no-gambling)**. La certificación de anuncios de
      *juego* es por sitio y por país: no la necesitas para empezar.
- [ ] Tener en cuenta: lotería es vertical sensible → menor fill/elegibilidad de anuncios.

## E. Google Play (opcional — más estricto que la web)

- [ ] Evaluar si publicas como app: el **generador de números** puede leerse como
      "funcionalidad de acompañamiento" de apuestas → riesgo de rechazo.
- [ ] Si publicas: integrar las **herramientas de verificación de edad de Play**
      (exigidas desde el 28-ene-2026 para features de juego/dinero).
- [ ] No incluir enlaces que dirijan a comprar lotería.
- [ ] Alternativa más segura: distribuir como **PWA instalable** (ya lo es) y dejar
      Play para una fase posterior, con asesoría.

## F. Modelo de ingresos (de menor a mayor fricción)

1. [ ] **Donaciones** (Nequi/Daviplata/Ko-fi) — botón simple, valida interés.
2. [ ] **AdSense estándar** sobre el contenido de resultados/estadísticas.
3. [ ] **Freemium/Pro** — cobrar por análisis avanzado, exportar, sin anuncios
       (vía Stripe/Lemon Squeezy/Gumroad). Encaja con el "modo Premium" actual.
4. [ ] **Alertas por suscripción** — push tras cada sorteo (conveniencia, no promesa).
5. [ ] **Vender el dataset / API** — el histórico limpio tiene valor para terceros.

## G. Antes de lanzar (revisión rápida)

- [ ] Reemplazados todos los `[campos]` de las plantillas.
- [ ] Correo de contacto real y monitoreado.
- [ ] Footer con enlaces a Juego responsable / Términos / Privacidad en todas las páginas.
- [ ] Datos reales cargados (`scraper.py --rebuild`) o datos de muestra claramente rotulados.
- [ ] Probado el age-gate y la instalación PWA en móvil.

---

### Recursos oficiales citados (verificar vigencia)

- Toma el Control (Coljuegos): https://tomaelcontrol.coljuegos.gov.co/
- Coljuegos: https://www.coljuegos.gov.co/
- Línea 106 — Salud mental (24/7, gratuita)
- Jugadores Anónimos (Barranquilla, Bogotá, Medellín, Cali, entre otras)
