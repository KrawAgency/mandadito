"""
revisar.py - Paso 3 del pipeline: valida los borradores de la extracción

Lee mandadito-proceso/borradores/*.json y escribe revision.json con, por
ticket, lo que encontró. No toca Firebase (solo lee sesiones/ y tickets/
para detectar duplicados). subir.py usa revision.json, no los borradores.

Qué revisa:
  - Fecha impresa válida (AAAA-MM-DD, no futura, no antes de 2025).
  - Tienda conocida (si no, aviso: hay que darla de alta en index.html).
  - Suma: Σ precio_unitario × cantidad contra el total. Hasta 5 centavos
    es redondeo; más de 50 centavos es problema.
  - Cada artículo: precio_unitario = (importe - descuento) / cantidad.
  - Privacidad: ningún texto puede traer 15 a 19 dígitos seguidos (una
    tarjeta; un código de barras tiene de 8 a 14) ni palabras de datos de
    pago. Cada foto de un ticket pagado con tarjeta debe estar en `ocultar`
    (una lista vacía quiere decir "revisada, no trae datos de la tarjeta").
  - Nombres: "catalogo" tiene que existir tal cual; "nuevo" no debe
    parecerse a uno existente (posible duplicado). El código de barras y la
    tabla de equivalencias mandan: si dicen otro producto, se avisa.
  - Duplicados: misma tienda (o mismo día y total con otra tienda) + fecha
    + total que una sesión ya registrada -> `duplicadoDe`. Además lista los
    artículos viejos que este ticket sustituye (`reemplaza`): los ligados a
    esa sesión y los sueltos (sin sesión) de la misma tienda y fecha.

Uso:
    python revisar.py
"""

import difflib
import json
import re
from collections import defaultdict
from datetime import date

from comun import (PROCESO, TIENDAS, a_firebase, a_iso, clave_producto,
                   get, guardar_json)
from contexto import cargar as cargar_contexto, candidatos, resolver

BORRADORES = PROCESO / "borradores"
REVISION = PROCESO / "revision.json"

CATEGORIAS = {
    "Frutas y Verduras", "Carnes y Pescados", "Lácteos", "Panadería",
    "Alimentos secos", "Conservas y Salsas", "Snacks", "Bebidas", "Congelados",
    "Higiene", "Cosméticos", "Hogar", "Farmacia", "Mascotas", "Electrónica",
    "Ferretería", "Ropa y calzado", "Papelería", "Flores y Plantas", "Autos",
    "Servicios", "Varios", "Por identificar",
}
PALABRAS_PAGO = re.compile(r"\b(AFILIACI|AUT(ORIZACI)?\b|ARQC|TARJETA\s*[:*x]|RFC\s*:|\*{4}\d{4})", re.I)
DIGITOS_LARGOS = re.compile(r"\d{15,19}")  # tarjeta; un EAN tiene de 8 a 14


def textos(obj, ruta=""):
    """Recorre todos los strings de un borrador, menos los códigos de barras."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("codigo", "fotos", "id", "ocultar", "rotar"):
                continue
            yield from textos(v, f"{ruta}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from textos(v, f"{ruta}[{i}]")
    elif isinstance(obj, str):
        yield ruta, obj


def revisar_ticket(t, ctx, sesiones, tickets, nuevos_lote):
    problemas, avisos = [], []

    # Fecha
    try:
        f = date.fromisoformat(t.get("fecha") or "")
        if f > date.today() or f.year < 2025:
            problemas.append(f"Fecha fuera de rango: {t['fecha']}")
    except ValueError:
        problemas.append(f"Fecha ilegible: '{t.get('fecha')}'")

    tienda = t.get("tienda", "")
    if tienda not in TIENDAS:
        avisos.append(f"Tienda nueva '{tienda}' ({t.get('sucursal', '')})")

    # Suma
    items = t.get("items") or []
    suma = round(sum(i["precio_unitario"] * i["cantidad"] for i in items), 2)
    total = t.get("total") or 0
    dif = round(total - suma, 2)
    t["suma"] = suma
    if abs(dif) > 0.5:
        problemas.append(f"La suma de artículos (${suma:,.2f}) no da el total (${total:,.2f}): faltan ${dif:,.2f}")
    elif abs(dif) > 0.05:
        avisos.append(f"Diferencia de ${dif:.2f} contra el total")

    # Artículos
    for n, i in enumerate(items, 1):
        esperado = round((i["importe"] - (i.get("descuento") or 0)) / i["cantidad"], 2)
        if abs(esperado - i["precio_unitario"]) > 0.02:
            problemas.append(f"Renglón {n} ({i['texto']}): precio unitario {i['precio_unitario']} no cuadra con importe y descuento ({esperado})")
        if i.get("categoria") not in CATEGORIAS:
            avisos.append(f"Renglón {n}: categoría '{i.get('categoria')}' no está en la lista")

        seguro, via = resolver(ctx, tienda, i["texto"], i.get("codigo"))
        if seguro and seguro != i["producto"]:
            avisos.append(f"Renglón {n} ({i['texto']}): el {via} dice '{seguro}', el borrador '{i['producto']}'")
            i["sugerido"] = seguro
        if i["match"] in ("catalogo", "codigo", "equivalencia") and i["producto"] not in ctx["productos"] and not seguro:
            if i["producto"] in nuevos_lote:
                i["match"] = "nuevo"
            else:
                avisos.append(f"Renglón {n}: '{i['producto']}' no existe en el catálogo; se tratará como nuevo")
                i["match"] = "nuevo"
        if i["match"] == "nuevo":
            parecidos = [c for c in candidatos(ctx, i["texto"], i["producto"], 3)
                         if difflib.SequenceMatcher(None, clave_producto(c), clave_producto(i["producto"])).ratio() >= 0.8]
            if parecidos:
                avisos.append(f"Renglón {n}: producto nuevo '{i['producto']}' se parece a '{parecidos[0]}'")
        i["candidatos"] = [c for c in candidatos(ctx, i["texto"], i["producto"], 3) if c != i["producto"]]

    # Privacidad
    for ruta, s in textos(t):
        if DIGITOS_LARGOS.search(s) or PALABRAS_PAGO.search(s):
            problemas.append(f"Posible dato de pago en {ruta}: revisar y borrar")
    if t.get("forma_pago") == "tarjeta":
        for foto in t.get("fotos", []):
            if foto not in (t.get("ocultar") or {}):
                problemas.append(f"Foto {foto} pagada con tarjeta sin bandas en 'ocultar'")

    # Duplicados contra Firebase
    fecha_fb = a_firebase(t["fecha"]) if a_iso(t.get("fecha")) else ""
    dup = None
    for sk, s in sesiones.items():
        if s.get("fecha") == fecha_fb and abs((s.get("total") or 0) - total) <= 0.05:
            if s.get("tienda") == tienda or dup is None:
                dup = sk
    reemplaza = []
    for k, it in tickets.items():
        if it.get("tipo") != "compra" or it.get("fecha") != fecha_fb:
            continue
        if (dup and it.get("sesion") == dup) or (not it.get("sesion") and it.get("tienda") == tienda):
            reemplaza.append(k)
    if dup:
        s = sesiones[dup]
        nota = f"Ya registrado como sesión {dup} ({s.get('tienda')}, ${s.get('total'):,.2f}, {len(reemplaza)} artículos)"
        if s.get("tienda") != tienda:
            nota += f" con tienda '{s.get('tienda')}' en lugar de '{tienda}'"
        avisos.append(nota)
    elif reemplaza:
        avisos.append(f"Hay {len(reemplaza)} artículos sueltos de {tienda} el {fecha_fb} sin sesión: este ticket los sustituye")

    return {
        "duplicadoDe": dup,
        "reemplaza": reemplaza,
        "problemas": problemas,
        "avisos": avisos,
    }


def main():
    ctx = cargar_contexto()
    sesiones = get("sesiones") or {}
    tickets = get("tickets") or {}
    borradores = sorted(BORRADORES.glob("*.json"))

    revision = []
    nuevos_lote = defaultdict(int)
    datos = [json.loads(p.read_text(encoding="utf-8")) for p in borradores]
    for t in datos:
        for i in t.get("items") or []:
            if i.get("match") == "nuevo":
                nuevos_lote[i["producto"]] += 1

    fuera = 0
    for t in datos:
        if t.get("tipo") != "ticket":
            fuera += 1
            continue
        t.update(revisar_ticket(t, ctx, sesiones, tickets, nuevos_lote))
        revision.append(t)

    # Nombres nuevos del lote que se parecen entre sí (mismo producto con dos nombres)
    nombres = list(nuevos_lote)
    for a in range(len(nombres)):
        for b in range(a + 1, len(nombres)):
            r = difflib.SequenceMatcher(None, clave_producto(nombres[a]), clave_producto(nombres[b])).ratio()
            if r >= 0.85:
                print(f"  [nombres nuevos parecidos] '{nombres[a]}' / '{nombres[b]}'")

    revision.sort(key=lambda t: t["fecha"])
    guardar_json(REVISION, revision)

    con_problemas = [t for t in revision if t["problemas"]]
    dups = [t for t in revision if t["duplicadoDe"]]
    print(f"\nTickets: {len(revision)}   No tickets: {fuera}")
    print(f"Con problemas: {len(con_problemas)}   Ya registrados: {len(dups)}   "
          f"Sustituyen artículos viejos: {sum(1 for t in revision if t['reemplaza'])}")
    print(f"Productos nuevos distintos: {len(nuevos_lote)}")
    for t in revision:
        if t["problemas"] or t["avisos"]:
            print(f"\n{t['id']}  {t['tienda']} {t['fecha']} ${t['total']:,.2f}")
            for p in t["problemas"]:
                print(f"   [PROBLEMA] {p}")
            for a in t["avisos"]:
                print(f"   [aviso] {a}")
    print(f"\nRevisión: {REVISION}")


if __name__ == "__main__":
    main()
