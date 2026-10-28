"""
aplicar.py - Paso 6 del pipeline: escribe en Firebase los tickets aprobados

pipeline/aprobados/{id} es lo que deja el botón "Aprobar" de la room
Pendientes: el ticket tal como quedó después de la revisión en el celular
(productos elegidos, artículos quitados, tienda y fecha corregidas) más
`reemplazar` (si se sustituyen los artículos viejos de ese ticket).

    python aplicar.py                (modo prueba: muestra qué escribiría)
    python aplicar.py --escribir     (respaldo + escritura)
    python aplicar.py --purgar-descartados [--forzar]

Por cada ticket aprobado arma UNA escritura múltiple (PATCH a la raíz, o
entra completa o no entra):

  sesiones/s_{id}            el ticket: tienda, fecha, total, ahorro, origen
  tickets/t_{id}_{n}         un artículo por renglón, ligado con `sesion`,
                             con `textoTicket` y `codigo` cuando hay
  catalogo/c_{id}_{n}        solo si ese producto no existe aún en esa
                             tienda (mismo criterio que regConfirmar en la app);
                             si existe y no tenía código, se le agrega
  codigos/{ean}              código de barras -> producto
  equivalencias/{tienda}/{TEXTO}
                             texto del ticket -> producto. Si ya apuntaba a
                             otro producto, se marca `ambiguo` y la extracción
                             deja de usarla (manda el código de barras)
  archivo/{id}/...           los artículos y la sesión viejos que este ticket
                             sustituye (si `reemplazar`), antes de borrarlos
  pipeline/aprobados/{id}, pipeline/imagenes/{id}  -> se borran

Antes de la primera escritura baja un respaldo completo; si falla, no
escribe nada. Si un id ya no está en pipeline/aprobados se salta
(idempotencia).
"""

import sys
from datetime import datetime, timedelta

from comun import (TIENDAS, a_firebase, clave_producto, clave_texto, delete,
                   get, patch, respaldo)

UMBRAL_DIAS_DESCARTE = 30


def ciudad_de(tienda, sucursal):
    s = (sucursal or "").lower()
    if "puerto morelos" in s:
        return "Puerto Morelos"
    if "playa del carmen" in s:
        return "Playa del Carmen"
    if "cancún" in s or "cancun" in s:
        return "Cancún"
    return TIENDAS.get(tienda, ("", "Puerto Morelos"))[1]


def notas_item(i):
    partes = []
    if i.get("granel"):
        g = i["granel"]
        partes.append(f"{g['peso_kg']:.3f}kg · ${g['precio_kg']:.2f}/kg")
    if i.get("descuento"):
        bruto = i["importe"] / i["cantidad"]
        partes.append(f"Promo {i.get('promo') or ''} → lista ${bruto:.2f} c/u, ahorro -${i['descuento']:.2f}".replace("  ", " "))
    if i.get("notas") and i["notas"] not in " · ".join(partes):
        partes.append(i["notas"])
    return " · ".join(p for p in partes if p)


def armar(id_, t, datos):
    """Devuelve el dict de escrituras para un ticket aprobado."""
    cambios = {}
    tienda = t["tienda"]
    fecha_fb = a_firebase(t["fecha"])
    ciudad = ciudad_de(tienda, t.get("sucursal"))
    sk = f"s_{id_}"
    items = [i for i in t.get("items") or [] if not i.get("quitado")]

    cambios[f"sesiones/{sk}"] = {
        "tienda": tienda,
        "etiquetaOriginal": t.get("sucursal") or TIENDAS.get(tienda, (tienda,))[0],
        "fecha": fecha_fb,
        "total": t["total"],
        "ahorro": t.get("ahorro") or 0,
        "notas": f"{len(items)} artículos · desde foto",
        "origen": "foto",
        "fotos": t.get("fotos") or [],
    }

    catalogo = datos.get("catalogo") or {}
    en_catalogo = {(clave_producto(c["producto"]), c.get("tienda")): k for k, c in catalogo.items()}
    equivalencias = datos.get("equivalencias") or {}

    for n, i in enumerate(items):
        producto = i["producto"].strip()
        item = {
            "fecha": fecha_fb, "tienda": tienda, "ciudad": ciudad,
            "producto": producto,
            "categoria": i.get("categoria", ""),
            "subcategoria": i.get("subcategoria", ""),
            "presentacion": i.get("presentacion", ""),
            "precio": round(i["precio_unitario"], 2),
            "cantidad": i["cantidad"],
            "notas": notas_item(i),
            "tipo": "compra",
            "sesion": sk,
            "textoTicket": i["texto"],
        }
        if i.get("codigo"):
            item["codigo"] = i["codigo"]
        cambios[f"tickets/t_{id_}_{n}"] = item

        clave = (clave_producto(producto), tienda)
        if clave in en_catalogo:
            existente = catalogo.get(en_catalogo[clave]) or {}
            if i.get("codigo") and not existente.get("codigo"):
                cambios[f"catalogo/{en_catalogo[clave]}/codigo"] = i["codigo"]
        else:
            ck = f"c_{id_}_{n}"
            cambios[f"catalogo/{ck}"] = {
                "producto": producto, "categoria": item["categoria"],
                "subcategoria": item["subcategoria"], "presentacion": item["presentacion"],
                "tienda": tienda, "ciudad": ciudad, "precio": item["precio"],
                "precioUnidad": f"${i['granel']['precio_kg']:.2f}/kg" if i.get("granel") else "",
                "notas": f"Desde ticket del {fecha_fb}",
                **({"codigo": i["codigo"]} if i.get("codigo") else {}),
            }
            en_catalogo[clave] = ck

        if i.get("codigo"):
            cambios[f"codigos/{i['codigo']}"] = {"producto": producto, "tienda": tienda, "actualizado": t["fecha"]}

        ct = clave_texto(i["texto"])
        if ct:
            previa = (equivalencias.get(tienda) or {}).get(ct) or {}
            nueva = {"producto": producto, "veces": (previa.get("veces") or 0) + 1,
                     "actualizado": t["fecha"], "origen": "aprobacion"}
            if previa and previa.get("producto") != producto:
                nueva["ambiguo"] = True
                nueva["alternativas"] = sorted({previa["producto"], *previa.get("alternativas", [])} - {producto})
            elif previa.get("ambiguo"):
                nueva["ambiguo"] = True
                nueva["alternativas"] = previa.get("alternativas", [])
            cambios[f"equivalencias/{tienda}/{ct}"] = nueva
            equivalencias.setdefault(tienda, {})[ct] = nueva

    # Sustituir lo viejo
    if t.get("reemplazar"):
        tickets = datos.get("tickets") or {}
        sesiones = datos.get("sesiones") or {}
        for k in t.get("reemplaza") or []:
            if k in tickets:
                cambios[f"archivo/{id_}/tickets/{k}"] = tickets[k]
                cambios[f"tickets/{k}"] = None
        dup = t.get("duplicadoDe")
        if dup and dup in sesiones:
            cambios[f"archivo/{id_}/sesiones/{dup}"] = sesiones[dup]
            cambios[f"sesiones/{dup}"] = None

    cambios[f"pipeline/aprobados/{id_}"] = None
    cambios[f"pipeline/imagenes/{id_}"] = None
    return cambios


def aplicar(escribir):
    aprobados = get("pipeline/aprobados") or {}
    if not aprobados:
        print("No hay nada en pipeline/aprobados.")
        return
    if escribir:
        print("Bajando respaldo antes de escribir...")
        if not respaldo("antes_aplicar"):
            print("Respaldo fallido - cancelo. No se escribió nada.")
            sys.exit(1)
    else:
        print("MODO PRUEBA - no se escribe nada. Usa --escribir.\n")

    for id_, t in sorted(aprobados.items()):
        datos = {n: get(n) or {} for n in ("tickets", "sesiones", "catalogo", "equivalencias")}
        if not t.get("reemplazar") and t.get("duplicadoDe") in datos["sesiones"]:
            print(f"  [ya registrado, se salta] {id_}: aprobado sin reemplazar y la sesión "
                  f"{t['duplicadoDe']} existe. Bórralo de pipeline/aprobados o apruébalo con reemplazo.")
            continue
        cambios = armar(id_, t, datos)
        n_items = sum(1 for k in cambios if k.startswith("tickets/t_"))
        n_borra = sum(1 for k, v in cambios.items() if v is None and k.startswith(("tickets/", "sesiones/")))
        n_cat = sum(1 for k in cambios if k.startswith("catalogo/c_"))
        resumen = (f"{id_}  {t['tienda']} {t['fecha']} ${t['total']:,.2f}: {n_items} artículos, "
                   f"{n_cat} productos nuevos en catálogo, {n_borra} registros viejos archivados")
        if not escribir:
            print(f"  [escribiría] {resumen}")
            continue
        if get(f"pipeline/aprobados/{id_}") is None:
            print(f"  [ya aplicado] {id_}")
            continue
        patch("", cambios)
        print(f"  [escrito] {resumen}")


def purgar_descartados(forzar=False):
    descartados = get("pipeline/descartados") or {}
    if not descartados:
        print("pipeline/descartados está vacío.")
        return
    limite = datetime.now() - timedelta(days=UMBRAL_DIAS_DESCARTE)
    for id_, d in descartados.items():
        try:
            cuando = datetime.fromisoformat((d.get("quitado_en") or "").replace("Z", "")[:19])
        except ValueError:
            cuando = datetime.now()
        if forzar or cuando < limite:
            delete(f"pipeline/descartados/{id_}")
            delete(f"pipeline/imagenes/{id_}")
            print(f"  [purgado] {id_}")
        else:
            print(f"  [conservado] {id_} (quitado el {cuando:%Y-%m-%d})")


def main():
    if "--purgar-descartados" in sys.argv:
        purgar_descartados("--forzar" in sys.argv)
    else:
        aplicar("--escribir" in sys.argv)


if __name__ == "__main__":
    main()
