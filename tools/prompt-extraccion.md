# Extracción de tickets — instrucciones para Claude Code

Paso 2 del pipeline. Antes de empezar: corre `preparar.py` y `contexto.py`, y
lee completo `C:\dev\mandadito-proceso\contexto.txt` (productos conocidos,
equivalencias y códigos).

Trabaja por tandas de ~10 grupos del `manifiesto.json`, en orden. Por cada
grupo mira sus fotos de `reducidas/` y escribe **un archivo por ticket** en
`C:\dev\mandadito-proceso\borradores\{id}.json`. Guarda cada archivo en
cuanto termines ese ticket: si la sesión se corta, lo hecho no se pierde.
Anota en `tandas.md` qué grupos quedaron.

## Privacidad (no negociable)

- **No transcribas** número de tarjeta (ni los últimos 4), afiliación,
  autorización, referencia bancaria, RFC del cliente ni nombre del cliente.
  Esos datos no van en ningún campo, ni en `notas`, ni en `dudas`.
- Sí puedes anotar la **forma de pago** en general ("tarjeta", "efectivo").
- Marca en `ocultar` las bandas de cada foto donde hay datos de pago o de
  tarjeta (bloque de pago, "PROMOCIONES DE BONIFICACION" con tarjeta,
  referencia): lista de `[y_inicio, y_fin]` en fracción de la altura
  (0 = arriba, 1 = abajo). Esas bandas se tapan en negro antes de subir la
  imagen a Firebase. Da un margen generoso. Los artículos, el total y la
  fecha deben quedar a la vista; en Chedraui la fecha va abajo del bloque
  de pago, por eso se tapan bandas y no se recorta.

## Formato

```json
{
  "id": "20260517_230856",
  "fotos": ["20260517_230856.jpg", "20260517_230903.jpg"],
  "tipo": "ticket",
  "tienda": "walmart",
  "sucursal": "Walmart Cancún Nichupté",
  "fecha": "2026-05-17",
  "hora": "22:58",
  "subtotal": 1520.40,
  "total": 1433.00,
  "ahorro": 87.40,
  "articulos_impresos": 30,
  "forma_pago": "tarjeta",
  "ocultar": {"20260517_230903.jpg": [[0.46, 0.52], [0.70, 0.80]]},
  "items": [
    {
      "texto": "LCH DESL 1L",
      "codigo": "7501020515466",
      "cantidad": 3,
      "importe": 165.00,
      "descuento": 25.00,
      "promo": "3x$140",
      "precio_unitario": 46.67,
      "granel": null,
      "producto": "Leche Santa Clara Deslactosada",
      "categoria": "Lácteos",
      "subcategoria": "Leche",
      "presentacion": "1L",
      "match": "catalogo",
      "confianza": "alta",
      "notas": ""
    }
  ],
  "dudas": ["El renglón 12 está borroso: leí 'PECH PV'"]
}
```

### Campos del ticket

- `id`: el `grupo` del manifiesto. Si el grupo resultó tener dos tickets,
  el segundo usa el nombre de su primera foto. Si una foto del grupo es de
  otro ticket, muévela al ticket correcto.
- `tipo`: `"ticket"`, o `"no_ticket"` si la foto no es un ticket de compra
  (etiqueta de anaquel, otra cosa). Para `no_ticket` basta `id`, `fotos`,
  `tipo` y en `dudas` qué es.
- `tienda`: clave de `comun.TIENDAS` (costco, walmart, chedraui, chedpm,
  aki, ml, pachamama, oceanleader, multiproteinas, aurrera, similares,
  delsol, oxxo, gomart, velvet). Chedraui de Puerto
  Morelos es `chedpm`; los de Cancún son `chedraui`. Si es otra tienda,
  inventa una clave corta en minúsculas y explícalo en `dudas`.
- `fecha` **impresa en el ticket**, en `AAAA-MM-DD`. Nunca la del nombre
  del archivo. Si no se lee, `""` y dilo en `dudas`.
- `subtotal`, `total`, `ahorro` (el "Ud. ahorró" / "Total de descuentos"
  impreso; si no hay, la suma de descuentos), `articulos_impresos` (el
  "No. de artículos" si viene): tal como están impresos; `null` si no
  aparecen.

### Campos por artículo

- `texto`: el nombre **tal como está impreso** ("LCH DESL 1L"). Es la llave
  de la tabla de equivalencias: no lo corrijas ni lo completes.
- `codigo`: el código de barras impreso en el renglón (Walmart lo imprime;
  8 a 14 dígitos). `null` si no hay.
- `cantidad`: piezas. Granel = 1.
- `importe`: lo que imprime el renglón (cantidad × precio de lista).
- `descuento`: suma de los renglones de promoción que le corresponden, en
  positivo. Los renglones "COMBINA 2X$13 -55.00", "3x$140", "AHORRO",
  "DESC" **no son artículos**: se restan al artículo al que se refieren
  (normalmente el de arriba). Si una promo abarca varios artículos
  distintos ("combina"), repártela en proporción al importe y anótalo en
  `notas`.
- `promo`: el texto de la promo, si hubo.
- `precio_unitario`: `(importe - descuento) / cantidad`, dos decimales. Es
  el precio real que se pagó por pieza.
- `granel`: para productos por peso, `{"peso_kg": 0.625, "precio_kg": 55.0}`
  y `cantidad` 1; `precio_unitario` es el importe.
- `producto`: el nombre canónico. En este orden:
  1. Si `codigo` está en "Códigos de barras conocidos" → ese producto,
     `match: "codigo"`.
  2. Si el `texto` está en "Equivalencias ya aprendidas" para esa tienda →
     ese producto, `match: "equivalencia"`.
  3. Si un producto conocido es claramente el mismo (misma marca, tipo y
     presentación) → su nombre **exacto, copiado letra por letra**,
     `match: "catalogo"`. Una presentación distinta (1L contra 3 pack) es
     otro producto.
  4. Si no hay ninguno → nombre nuevo con las reglas de abajo,
     `match: "nuevo"`. Antes de inventarlo, busca en la lista por marca
     y por tipo para no duplicar.
- `categoria`, `subcategoria`: de la lista válida de abajo.
- `confianza`: `"alta"` si el texto es claro y el match seguro; `"baja"` si
  el texto está truncado, borroso o el match es una suposición. Con
  `"baja"` igual da tu mejor propuesta.
- `notas`: corto. Para granel "0.625kg · $55.00/kg".

### Reglas de nombres (de "Instrucciones Registro Compras")

- Title Case: "Leche Santa Clara Deslactosada", no "LECHE SANTA CLARA".
- Marca + descripción + presentación si ayuda a distinguir.
- Granel termina en "a granel": "Papa Blanca a granel".
- Huevo: "Huevo [Marca] [tipo] [cantidad]" → "Huevo Bachoco Blanco 30 pzas".
- No abreviar: "desodorante", no "deso".

### Categorías válidas

Frutas y Verduras · Carnes y Pescados (Res, Cerdo, Ave, Embutidos, Mariscos,
Pescado) · Lácteos (Leche, Quesos, Yogurt, Crema, Kéfir, Huevo, Cacao,
Mantequilla) · Panadería (Pan de caja, Pan dulce, Tortillas, Pasteles) ·
Alimentos secos (Cereales, Leguminosas, Semillas, Frutos secos, Arroz y
pasta, Básicos, Aceites, Endulzantes, Harinas) · Conservas y Salsas (Latas,
Salsas, Aderezos, Mermeladas) · Snacks (Galletas, Barras, Totopos, Dulces,
Botanas, Chicles) · Bebidas (Jugos, Refrescos, Café, Té e infusiones, Agua,
Bebidas deportivas, Bebidas energéticas, Alcohol) · Congelados (Frutas,
Verduras, Carnes, Comidas preparadas, Helados) · Higiene (Desodorante,
Jabón, Shampoo, Acondicionador, Dental, Femenino, Cabello, Corporal,
Afeitado, Pañales) · Cosméticos (Cremas faciales, Cremas corporales,
Maquillaje, Perfumes, Protector solar) · Hogar (Detergente ropa,
Limpiadores, Papel, Insecticidas, Velas y aromas, Utensilios cocina,
Organización) · Farmacia (Medicamentos, Vitaminas, Primeros auxilios,
Hidratación oral, Repelente, Anticonceptivos) · Mascotas (Alimento perro,
Alimento gato, Alimento aves, Accesorios) · Electrónica · Ferretería ·
Ropa y calzado · Papelería · Flores y Plantas · Autos · Servicios · Varios ·
Por identificar.

## Antes de cerrar cada ticket

Suma `precio_unitario × cantidad` de todos los artículos. Debe dar el
`total` (o el `subtotal` si el ticket desglosa IVA aparte). Si no da, revisa
renglones de promo que no restaste o artículos que se te pasaron. Si sigue
sin cuadrar, deja la diferencia explicada en `dudas`: `revisar.py` la va a
marcar y la revisión en el celular la verá.
