# Mandadito

Lista del súper compartida en tiempo real (Fernando y su esposa), catálogo de
productos, historial de precios por tienda y registro de tickets. PWA de un solo
archivo (`index.html`, sin build) en GitHub Pages (`krawagency.github.io/mandadito/`)
con Firebase Realtime Database (proyecto `compras-visor`). Los tickets entran por
foto con el pipeline de `tools/`.

## Reglas de trabajo

- Cambios a `index.html` uno por uno, en commits separados, con aprobación de
  Fernando. Cambios quirúrgicos, no reescrituras.
- Nada escribe en `tickets/`, `sesiones/` ni `catalogo/` sin respaldo previo:
  los scripts bajan la base completa a `C:\dev\mandadito-proceso\respaldos\`
  y cancelan si el respaldo falla.
- La app solo escribe en `lista`, en el registro manual de tickets, en la
  edición de registros y en `pipeline/respuestas` (pestaña Dudas).
- Datos de pago (tarjeta, afiliación, autorización, ARQC) y RFC del cliente: no
  se transcriben y se tapan en las fotos antes de subirlas.
- Validar la sintaxis del JS antes de probar: extraer el `<script>` principal y
  `node --check`.
- Lecciones viejas: no volver a pintar un modal completo mientras se escribe en
  un input (pierde el foco); cuidado con reglas CSS duplicadas que pisan la
  visibilidad de las pestañas.

## Datos (Firebase)

| Nodo | Qué es | Llave |
|---|---|---|
| `sesiones/{id}` | Un ticket: tienda, fecha `DD/MM/AAAA`, total, ahorro, notas; `origen: "foto"` y `fotos` si vino del pipeline | `s0000`, `s_{timestamp}`, `s_{idFoto}` |
| `tickets/{id}` | **Un artículo** (no un ticket): producto, categoría, precio **por pieza ya con descuento**, cantidad, `sesion` (liga con su ticket), `textoTicket` y `codigo` si vino de foto | `t0000`, `t_{ts}_{n}`, `t_{idFoto}_{n}` |
| `catalogo/{id}` | Precio de referencia por producto **y tienda**; `codigo` si se conoce | `c0000`, `c_{...}` |
| `codigos/{ean}` | Código de barras → producto canónico | EAN |
| `equivalencias/{tienda}/{TEXTO}` | Texto tal como lo imprime la tienda → producto. `ambiguo: true` si el mismo texto se aprobó con dos productos (entonces manda el código) | texto normalizado |
| `lista` | La lista del súper compartida | arreglo |
| `pipeline/pendientes`, `imagenes` | Tickets subidos que aún no guarda `aplicar.py`; fotos con los datos de pago tapados | id de la foto |
| `pipeline/preguntas`, `respuestas` | Dudas por renglón (una por texto de ticket) y lo que contestó Fernando | `{tienda}__{TEXTO}` |
| `archivo/{id}/...` | Lo que un ticket aprobado sustituyó (artículos y sesión viejos) | id de la foto |

- El producto se identifica **por nombre** (así lo usa toda la app). Renombrar
  con "Modificar todos" no actualiza `codigos/` ni `equivalencias/`.
- Granel: `cantidad` 1 y `precio` = importe pagado; peso y precio por kilo van en notas.
- Las reglas de Firebase están abiertas (lectura y escritura sin login). Ver
  `docs/ARQUITECTURA.md`.

## Mapa de `index.html`

Buscar por el encabezado `// ═══` de cada módulo (los números de línea cambian):

- `<script type="module">`: inicializa Firebase y expone `_fbGet`, `_fbWrite` (set de un nodo; `null` borra), `_fbSet`/`_fbListen` (lista).
- Diseño: paleta del logo en `:root` (crema, naranja `--accent`, café), tipografía Nunito, logo en `logo-icono.png` y `logo-texto.png` (recortes de `logo-completo.png`). Las vistas de Tickets, Catálogo y Resumen son tarjetas, no tablas.
- `CONFIGURACIÓN DE TIENDAS`: `CONFIG_TIENDAS` (clave, etiqueta, color). Una tienda nueva se agrega aquí y en `tools/comun.py` (`TIENDAS`).
- `CARGA DE DATOS`: `cargarDatos()` llena `TICKETS`, `CATALOGO`, `SESIONES` y los ordena por fecha (`fechaISO`).
- `CONSTRUCCIÓN DE LA UI`: tablas, `SECCIONES` (pestañas), `actualizarSeccion`, `navegar`.
- `MÓDULO: LISTA DE COMPRAS`, `PICKER DE CATÁLOGO`, `EDICIÓN DE REGISTROS` (`editEscribir` combina con el registro original para no perder campos), `REGISTRO DE TICKET` (captura manual por JSON).
- `MÓDULO: DUDAS`: preguntas por renglón (`dudasRender`, `dudaResponder`); escribe `pipeline/respuestas`.

## Pipeline de tickets por foto (`tools/`)

Python con librería estándar más Pillow. Carpeta de trabajo: `C:\dev\mandadito-proceso`
(fuera del repo; ahí quedan manifiesto, borradores, revisión, imágenes y respaldos).

1. `python tools/preparar.py`: fotos nuevas de `C:\GoogleDrive\Tickets-compras`, con `exif_transpose`, a 1568 px, y las agrupa por cercanía (menos de 3 min).
2. `python tools/contexto.py`, y luego extraer con Claude Code siguiendo `tools/prompt-extraccion.md`: un `borradores/{id}.json` por ticket, por tandas de ~10 grupos (anotar en `tandas.md`).
3. `python tools/revisar.py`: fecha, tienda, suma contra el total, precio por pieza, privacidad, nombres nuevos parecidos a existentes y duplicados contra `sesiones/`. Escribe `revision.json`.
4. `python tools/subir.py`, y luego `--subir`: a `pipeline/pendientes`, con las imágenes tapadas (revisarlas en `subidas/`).
5. `python tools/aplicar.py`, y luego `--escribir`: respaldo y guarda cada ticket tal cual (sin aprobación por ticket), sustituyendo lo capturado antes de ese día. Los renglones con `preguntar` se vuelven una pregunta por texto en `pipeline/preguntas`; las respuestas de la pestaña Dudas (`pipeline/respuestas`) se aplican en la siguiente corrida. `--purgar-descartados` limpia lo descartado.

`tools/limpiar_historico.py` fue un arreglo de una sola vez de los datos viejos
(ya aplicado el 2026-10-28; correrlo otra vez no cambia nada).
