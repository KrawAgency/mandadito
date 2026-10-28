# Arquitectura y decisiones (2026-10-28)

Revisión completa de Mandadito al retomarlo: qué estaba mal, qué se cambió y qué
queda pendiente. Respaldos de cada paso en `C:\dev\mandadito-proceso\respaldos\`.

## Diagnóstico de los datos

Al empezar había 392 registros en `tickets/` (artículos, no tickets), 29
sesiones y 196 filas de catálogo:

- **Importaciones dobles.** Walmart 01/06 y Pachamama 04/06 venían dos veces
  completas (sesión y artículos). Pachamama 12/05, Chedraui P.M. 19/05 y
  Pachamama 19/05 estaban a mano y otra vez en la importación de junio.
- **Precio con dos significados.** A veces era por pieza y a veces el total del
  renglón, y en la captura a mano de algunos días era el precio por kilo.
- **Granel con cantidad 0.** 49 artículos no sumaban en ningún total.
- **Artículos sin ticket.** Nada ligaba un artículo con su sesión. Con dos
  tickets el mismo día en la misma tienda no había forma de separarlos.
- **Tienda equivocada.** Tres tickets de Super Aki estaban como Chedraui P.M.
- **Tiendas sin alta en la app.** Ocean Leader y Multiproteínas tenían datos
  pero no estaban en `CONFIG_TIENDAS`: salían sin etiqueta, y al editar uno se
  cambiaba a Costco.
- **Editar borraba campos.** `editEscribir` reescribía el registro solo con
  los campos del formulario.
- **Orden de fechas.** `DD/MM/AAAA` se ordenaba como texto.

## Qué se hizo

| Cambio | Dónde | Cómo se revierte |
|---|---|---|
| Limpieza del histórico (8 reglas, 346 escrituras) | `tools/limpiar_historico.py` | Respaldos `antes_limpieza_*.json`; bitácoras `limpieza_*.json` |
| Pipeline de tickets por foto | `tools/` | No toca datos hasta `aplicar.py --escribir` |
| 93 fotos extraídas: 56 tickets a Pendientes, 15 grupos descartados (restaurantes, vouchers, copias, recibos) | `mandadito-proceso/borradores` | `pipeline/` se puede borrar sin afectar datos |
| 1 ticket aprobado y aplicado de prueba (Chedraui P.M. 20/10/2026, $61.17) | Firebase | Respaldo `antes_aplicar_*.json` |
| Room Pendientes y 5 arreglos en `index.html` | rama `pipeline-tickets` | Un commit por cambio |

Después de la limpieza: 28 sesiones y 331 artículos. 14 sesiones cuadran al
centavo con sus artículos. De las otras 14, 13 tienen foto en Pendientes y
quedan bien al aprobarlas con "Sustituir". La única que queda sin foto es
Chedraui P.M. del 13/04/2026 ($169.16).

## Empatar nombres del ticket con el catálogo

Cascada por renglón (`contexto.resolver` y `prompt-extraccion.md`):

1. **Código de barras** en `codigos/` (Walmart, Bodega Aurrera y Costco lo imprimen). Es determinista.
2. **Equivalencia aprendida** `equivalencias/{tienda}/{TEXTO}`. Se ignora si está marcada `ambiguo`.
3. **Producto del catálogo** elegido por la extracción entre los nombres conocidos, con candidatos por similitud (difflib) para la revisión.
4. **Nuevo**, solo si no hay ninguno. `revisar.py` avisa si se parece a uno existente.

Cada aprobación enseña: `aplicar.py` escribe la equivalencia del texto y el
código. Si el mismo texto se aprueba con otro producto ("TOSTADAS" son dos
productos de Salmas, "YOPLAIT KG" dos yogures), se marca `ambiguo` y a partir de
ahí decide el código de barras. Las equivalencias son por tienda porque cada
cadena abrevia distinto. Los códigos son globales.

## Promociones y precio real

El precio que se guarda es por pieza y ya con descuento:
`(importe − descuento) / cantidad`. Los renglones de promo ("COMBINA 2X$13
-55.00", "Multiahorro 3", "3x2") se restan al artículo al que se refieren. Si
una promo abarca varios productos, se reparte en proporción al importe. El
precio de lista y el ahorro quedan en `notas`. El ahorro del ticket va en la
sesión. Las bonificaciones a monedero de Chedraui no restan, porque no bajan el
total pagado.

## Privacidad

- La extracción no transcribe tarjeta, afiliación, autorización, ARQC, RFC del
  cliente ni nombres. `revisar.py` rechaza cualquier texto con 15 a 19 dígitos
  seguidos o con palabras de pago.
- Las fotos se suben a Firebase con esas bandas tapadas en negro: se tapan
  sobre la foto ya derecha y se revisan en `subidas/`. Las imágenes se borran
  de Firebase al aplicar o al purgar los descartados.

## Pendiente (decisiones de Fernando)

1. **Publicar la rama** `pipeline-tickets` en `main`. Hasta entonces la app
   publicada no tiene la pestaña Pendientes.
2. **Revisar los 55 tickets pendientes.** Los que no son súper llegan igual
   para que decida: pintura en Costco (3 tickets, $7,817), renovación de la
   membresía de Costco ($599.95, dentro del ticket del 21/09), papelería, 2 de
   farmacia, Oxxo, GoMart y dulcería Del Sol.
3. **Reglas de Firebase abiertas.** Cualquiera con la URL puede leer y
   escribir. Lo recomendable es Firebase Auth con Google para los dos
   celulares y reglas `auth != null`. Cambia la app y los scripts (que hoy
   escriben por REST sin token), así que queda como tarea aparte.
4. **Correr el pipeline cada cierto tiempo.** Hoy es manual en Claude Code. Se
   puede encadenar como `orquestar.py` de NutriLog cuando el flujo se estabilice.
5. **Reinstalar la PWA** en los dos celulares desde la URL nueva (pendiente
   desde el cambio de nombre).
