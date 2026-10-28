"""
aplicar.py - Paso 5 del pipeline: guarda los tickets y aplica las respuestas

Los tickets no se aprueban uno por uno. Lo que subió subir.py a
pipeline/pendientes se guarda tal cual, con la mejor lectura de la
extracción. Solo los renglones que la extracción marcó con `preguntar`
(nombre que puede ser varias cosas y cambia la comparación de precios) se
vuelven una pregunta en pipeline/preguntas/{tienda}__{TEXTO}: una por texto
de ticket, aunque ese texto salga en varios tickets. Fernando contesta en la
pestaña Dudas de la app (pipeline/respuestas/{id}) y la siguiente corrida
corrige esos artículos.

    python aplicar.py                (modo prueba: muestra qué haría)
    python aplicar.py --escribir     (respaldo + escritura)
    python aplicar.py --purgar-descartados [--forzar]

Por cada ticket, UNA escritura múltiple (PATCH a la raíz: entra completa o no
entra):

  sesiones/s_{id}            el ticket: tienda, fecha, total, ahorro, origen
  tickets/t_{id}_{n}         un artículo por renglón, ligado con `sesion`,
                             con `textoTicket` y `codigo` cuando hay
  catalogo/c_{id}_{n}        solo si ese producto no existe aún en esa tienda;
                             si existe y no tenía código, se le agrega
  codigos/{ean}              código de barras -> producto
  equivalencias/{tienda}/{TEXTO}
                             texto del ticket -> producto. Si ya apuntaba a
                             otro producto, se marca `ambiguo` y la extracción
                             deja de usarla (manda el código de barras)
  archivo/{id}/...           los artículos y la sesión viejos que este ticket
                             sustituye, antes de borrarlos (la foto manda sobre
                             lo capturado a mano)
  pipeline/preguntas/{qid}   las dudas de ese ticket (se conserva su imagen)

Por cada respuesta: corrige producto y categoría de los artículos (o los
quita), deja la equivalencia confirmada, da de alta el producto en el
catálogo si hace falta y borra la fila que la lectura había creado de más.

Antes de la primera escritura baja un respaldo completo; si falla, no
escribe nada.
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


def id_pregunta(tienda, texto):
    return f"{tienda}__{clave_texto(texto).replace(' ', '_')}"


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


def alta_catalogo(cambios, catalogo, en_catalogo, clave_nueva, item, codigo=None, precio_kg=None):
    """Agrega el producto al catálogo de esa tienda si no está; si está, le pone el código."""
    clave = (clave_producto(item["producto"]), item["tienda"])
    if clave in en_catalogo:
        existente = catalogo.get(en_catalogo[clave]) or {}
        if codigo and not existente.get("codigo"):
            cambios[f"catalogo/{en_catalogo[clave]}/codigo"] = codigo
        return
    cambios[f"catalogo/{clave_nueva}"] = {
        "producto": item["producto"], "categoria": item["categoria"],
        "subcategoria": item["subcategoria"], "presentacion": item.get("presentacion", ""),
        "tienda": item["tienda"], "ciudad": item["ciudad"], "precio": item["precio"],
        "precioUnidad": f"${precio_kg:.2f}/kg" if precio_kg else "",
        "notas": f"Desde ticket del {item['fecha']}",
        **({"codigo": codigo} if codigo else {}),
    }
    en_catalogo[clave] = clave_nueva


def armar(id_, t, datos, origen):
    """Escrituras para guardar un ticket. Devuelve (cambios, preguntas nuevas {qid: pregunta})."""
    cambios = {}
    tienda = t["tienda"]
    fecha_fb = a_firebase(t["fecha"])
    ciudad = ciudad_de(tienda, t.get("sucursal"))
    sk = f"s_{id_}"
    items = t.get("items") or []
    vivos = [i for i in items if not i.get("quitado")]

    cambios[f"sesiones/{sk}"] = {
        "tienda": tienda,
        "etiquetaOriginal": t.get("sucursal") or TIENDAS.get(tienda, (tienda,))[0],
        "fecha": fecha_fb,
        "total": t["total"],
        "ahorro": t.get("ahorro") or 0,
        "notas": f"{len(vivos)} artículos · desde foto",
        "origen": "foto",
        "fotos": t.get("fotos") or [],
    }

    catalogo = datos.get("catalogo") or {}
    en_catalogo = {(clave_producto(c["producto"]), c.get("tienda")): k for k, c in catalogo.items()}
    equivalencias = datos.get("equivalencias") or {}
    preguntas_existentes = datos.get("preguntas") or {}
    preguntas = {}

    for n, i in enumerate(items):
        if i.get("quitado"):
            continue
        producto = i["producto"].strip()
        tk = f"t_{id_}_{n}"
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
        cambios[f"tickets/{tk}"] = item
        alta_catalogo(cambios, catalogo, en_catalogo, f"c_{id_}_{n}", item,
                      i.get("codigo"), (i.get("granel") or {}).get("precio_kg"))

        if i.get("codigo"):
            cambios[f"codigos/{i['codigo']}"] = {"producto": producto, "tienda": tienda, "actualizado": t["fecha"]}

        ct = clave_texto(i["texto"])
        if ct:
            previa = (equivalencias.get(tienda) or {}).get(ct) or {}
            nueva = {"producto": producto, "veces": (previa.get("veces") or 0) + 1,
                     "actualizado": t["fecha"], "origen": origen}
            if previa.get("confirmada"):
                nueva.update(producto=previa["producto"], confirmada=True)
            elif previa and previa.get("producto") != producto:
                nueva["ambiguo"] = True
                nueva["alternativas"] = sorted({previa["producto"], *previa.get("alternativas", [])} - {producto})
            elif previa.get("ambiguo"):
                nueva["ambiguo"] = True
                nueva["alternativas"] = previa.get("alternativas", [])
            cambios[f"equivalencias/{tienda}/{ct}"] = nueva
            equivalencias.setdefault(tienda, {})[ct] = nueva

        # Dudas: una pregunta por texto de ticket; los demás renglones con el
        # mismo texto (en este ticket o en otros) se cuelgan de la misma.
        qid = id_pregunta(tienda, i["texto"])
        if i.get("preguntar") or qid in preguntas or qid in preguntas_existentes:
            q = preguntas.get(qid) or dict(preguntas_existentes.get(qid) or {})
            if not q:
                q = {"tienda": tienda, "texto": i["texto"], "porque": "", "opciones": [],
                     "precio": item["precio"], "fecha": t["fecha"], "items": [], "fotos": []}
            if i.get("preguntar"):
                q["porque"] = i["preguntar"].get("porque", q["porque"])
                q["opciones"] = i["preguntar"].get("opciones") or q["opciones"]
            if not any(o.get("producto") == producto for o in q["opciones"]):
                q["opciones"] = [{"producto": producto, "categoria": item["categoria"],
                                  "subcategoria": item["subcategoria"]}] + q["opciones"]
            q["items"] = sorted(set(q.get("items", []) + [tk]))
            q["fotos"] = sorted(set(q.get("fotos", []) + [id_]))
            preguntas[qid] = q

    # La foto manda: sustituir lo capturado antes de ese ticket
    if t.get("reemplazar", True):
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

    for qid, q in preguntas.items():
        cambios[f"pipeline/preguntas/{qid}"] = q
    cambios[f"pipeline/{origen}/{id_}"] = None
    if not preguntas:
        cambios[f"pipeline/imagenes/{id_}"] = None
    return cambios, preguntas


def armar_respuesta(qid, q, r, datos):
    """Escrituras para aplicar una respuesta de la pestaña Dudas."""
    cambios = {}
    tickets = datos.get("tickets") or {}
    catalogo = datos.get("catalogo") or {}
    en_catalogo = {(clave_producto(c["producto"]), c.get("tienda")): k for k, c in catalogo.items()}
    viejos = set()

    for tk in q.get("items") or []:
        it = tickets.get(tk)
        if not it:
            continue
        viejos.add(it["producto"])
        if r.get("quitar"):
            cambios[f"archivo/respuestas/{qid}/{tk}"] = it
            cambios[f"tickets/{tk}"] = None
            continue
        nuevo = dict(it, producto=r["producto"].strip(),
                     categoria=r.get("categoria") or it.get("categoria", ""),
                     subcategoria=r.get("subcategoria", it.get("subcategoria", "")))
        if r.get("presentacion"):
            nuevo["presentacion"] = r["presentacion"]
        cambios[f"tickets/{tk}"] = nuevo
        alta_catalogo(cambios, catalogo, en_catalogo, f"c_{tk[2:]}", nuevo, it.get("codigo"))
        if it.get("codigo"):
            cambios[f"codigos/{it['codigo']}"] = {"producto": nuevo["producto"], "tienda": it["tienda"]}

    # Filas de catálogo que la lectura creó para el nombre que resultó equivocado
    restantes = {v["producto"] for k, v in tickets.items() if f"tickets/{k}" not in cambios}
    for k, c in catalogo.items():
        if c["producto"] in viejos and c["producto"] not in restantes and k.startswith("c_") \
                and (r.get("quitar") or c["producto"] != r.get("producto")):
            cambios[f"catalogo/{k}"] = None

    ct = clave_texto(q["texto"])
    if not r.get("quitar"):
        cambios[f"equivalencias/{q['tienda']}/{ct}"] = {
            "producto": r["producto"].strip(), "confirmada": True, "origen": "respuesta",
            "actualizado": datetime.now().strftime("%Y-%m-%d"),
        }
    cambios[f"pipeline/preguntas/{qid}"] = None
    cambios[f"pipeline/respuestas/{qid}"] = None
    return cambios


def correr(escribir):
    pendientes = get("pipeline/pendientes") or {}
    aprobados = get("pipeline/aprobados") or {}   # flujo anterior, por si quedó algo
    respuestas = get("pipeline/respuestas") or {}
    if not (pendientes or aprobados or respuestas):
        print("Nada que guardar: sin tickets nuevos ni respuestas.")
        return
    if escribir:
        print("Bajando respaldo antes de escribir...")
        if not respaldo("antes_aplicar"):
            print("Respaldo fallido - cancelo. No se escribió nada.")
            sys.exit(1)
    else:
        print("MODO PRUEBA - no se escribe nada. Usa --escribir.\n")

    def leer():
        d = {n: get(n) or {} for n in ("tickets", "sesiones", "catalogo", "equivalencias")}
        d["preguntas"] = get("pipeline/preguntas") or {}
        return d

    n_tickets = n_preg = 0
    datos = leer()
    for origen, lote in (("aprobados", aprobados), ("pendientes", pendientes)):
        for id_, t in sorted(lote.items(), key=lambda kv: kv[1].get("fecha", "")):
            cambios, preguntas = armar(id_, t, datos, origen)
            n_items = sum(1 for k in cambios if k.startswith("tickets/t_") and cambios[k])
            n_borra = sum(1 for k, v in cambios.items() if v is None and k.startswith(("tickets/", "sesiones/")))
            resumen = (f"{id_}  {t['tienda']} {t['fecha']} ${t['total']:,.2f}: {n_items} artículos"
                       + (f", sustituye {n_borra} registros viejos" if n_borra else "")
                       + (f", {len(preguntas)} duda(s)" if preguntas else ""))
            n_tickets += 1
            if not escribir:
                print(f"  [guardaría] {resumen}")
                datos["preguntas"].update(preguntas)
                continue
            patch("", cambios)
            print(f"  [guardado] {resumen}")
            datos = leer()

    for qid, r in respuestas.items():
        q = datos["preguntas"].get(qid)
        if not q:
            print(f"  [respuesta sin pregunta] {qid}: se borra")
            if escribir:
                delete(f"pipeline/respuestas/{qid}")
            continue
        cambios = armar_respuesta(qid, q, r, datos)
        quedan = {f for p, x in datos["preguntas"].items() if p != qid for f in x.get("fotos", [])}
        for f in q.get("fotos", []):
            if f not in quedan:
                cambios[f"pipeline/imagenes/{f}"] = None
        que = "quitar" if r.get("quitar") else f"→ {r.get('producto')}"
        n_preg += 1
        if not escribir:
            print(f"  [respondería] {q['tienda']} «{q['texto']}» {que} ({len(q.get('items', []))} artículos)")
            continue
        patch("", cambios)
        print(f"  [respuesta] {q['tienda']} «{q['texto']}» {que} ({len(q.get('items', []))} artículos)")
        datos = leer()

    total_preg = len(get("pipeline/preguntas") or {}) if escribir else len(datos["preguntas"])
    print(f"\nTickets: {n_tickets}   Respuestas aplicadas: {n_preg}   Dudas abiertas: {total_preg}")


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
        correr("--escribir" in sys.argv)


if __name__ == "__main__":
    main()
