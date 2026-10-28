"""
contexto.py - Lo que la extracción necesita saber del catálogo

Baja de Firebase los nombres de producto conocidos (tickets + catálogo),
la tabla de equivalencias y el índice de códigos, y escribe:

  mandadito-proceso/contexto.json   (lo usan revisar.py y subir.py)
  mandadito-proceso/contexto.txt    (versión compacta para leer al extraer)

También expone `candidatos(texto, producto, tienda)` para sugerir los
nombres más parecidos (difflib, sin dependencias).

Uso:
    python contexto.py
"""

import difflib
from collections import Counter, defaultdict

from comun import PROCESO, cargar_json, clave_producto, clave_texto, get, guardar_json

CONTEXTO_JSON = PROCESO / "contexto.json"
CONTEXTO_TXT = PROCESO / "contexto.txt"


def construir():
    datos = {n: get(n) or {} for n in ("tickets", "catalogo", "equivalencias", "codigos")}
    productos = {}
    usos = Counter()
    tiendas = defaultdict(set)
    for nodo in ("catalogo", "tickets"):
        for r in datos[nodo].values():
            nombre = r.get("producto", "").strip()
            if not nombre or "SIN IDENTIFICAR" in nombre.upper():
                continue
            usos[nombre] += 1
            tiendas[nombre].add(r.get("tienda", ""))
            p = productos.setdefault(nombre, {
                "categoria": r.get("categoria", ""),
                "subcategoria": r.get("subcategoria", ""),
                "presentacion": r.get("presentacion", ""),
            })
            if not p["presentacion"] and r.get("presentacion"):
                p["presentacion"] = r["presentacion"]
    for nombre, p in productos.items():
        p["usos"] = usos[nombre]
        p["tiendas"] = sorted(t for t in tiendas[nombre] if t)
    return {
        "productos": productos,
        "equivalencias": datos["equivalencias"],
        "codigos": datos["codigos"],
    }


def cargar():
    return cargar_json(CONTEXTO_JSON, None) or construir()


def candidatos(ctx, texto="", producto="", n=3):
    """Los n nombres conocidos más parecidos al texto del ticket o al nombre propuesto."""
    nombres = list(ctx["productos"])
    claves = {clave_producto(x): x for x in nombres}
    puntos = Counter()
    for consulta in (producto, texto):
        if not consulta:
            continue
        q = clave_producto(consulta)
        for c in difflib.get_close_matches(q, list(claves), n=n * 2, cutoff=0.45):
            puntos[claves[c]] = max(puntos[claves[c]], difflib.SequenceMatcher(None, q, c).ratio())
    return [nombre for nombre, _ in puntos.most_common(n)]


def resolver(ctx, tienda, texto, codigo):
    """
    Busca un acierto seguro: primero el código de barras, luego la tabla de
    equivalencias de esa tienda. Devuelve (producto, "codigo"|"equivalencia")
    o (None, None).
    """
    if codigo and codigo in ctx["codigos"]:
        return ctx["codigos"][codigo]["producto"], "codigo"
    eq = (ctx["equivalencias"].get(tienda) or {}).get(clave_texto(texto))
    if eq and not eq.get("ambiguo"):
        return eq["producto"], "equivalencia"
    return None, None


def main():
    ctx = construir()
    guardar_json(CONTEXTO_JSON, ctx)
    lineas = ["# Productos conocidos (nombre | categoría / subcategoría | presentación | tiendas)"]
    por_cat = defaultdict(list)
    for nombre, p in ctx["productos"].items():
        por_cat[p["categoria"]].append((nombre, p))
    for cat in sorted(por_cat):
        lineas.append(f"\n## {cat}")
        for nombre, p in sorted(por_cat[cat]):
            lineas.append(f"{nombre} | {p['subcategoria']} | {p['presentacion']} | {','.join(p['tiendas'])}")
    lineas.append("\n# Equivalencias ya aprendidas (tienda: TEXTO DEL TICKET -> producto)")
    for tienda, tabla in ctx["equivalencias"].items():
        for texto, eq in tabla.items():
            lineas.append(f"{tienda}: {texto} -> {eq['producto']}")
    lineas.append("\n# Códigos de barras conocidos")
    for ean, c in ctx["codigos"].items():
        lineas.append(f"{ean} -> {c['producto']}")
    CONTEXTO_TXT.write_text("\n".join(lineas), encoding="utf-8")
    print(f"{len(ctx['productos'])} productos, "
          f"{sum(len(t) for t in ctx['equivalencias'].values())} equivalencias, "
          f"{len(ctx['codigos'])} códigos")
    print(f"Contexto: {CONTEXTO_TXT}")


if __name__ == "__main__":
    main()
