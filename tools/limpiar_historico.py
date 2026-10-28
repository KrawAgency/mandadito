"""
limpiar_historico.py - Arreglos de una sola vez a los datos viejos de Firebase

Los 392 artículos y 29 sesiones se cargaron a mano en varias etapas (may-jun
2026) y quedaron con errores. Este script los corrige con reglas explícitas,
cada una con su motivo. No inventa datos: solo corrige lo que se puede
deducir de los propios registros.

  1. Importación duplicada: Walmart 01/06/2026 y Pachamama 04/06/2026 se
     cargaron dos veces (lotes t_1780745521928 / t_1780744642434 y luego
     otra vez en t_1781590041567). Se conserva la primera carga, que trae el
     texto del ticket y los códigos en notas, y se borra la segunda.
  2. cantidad 0 en productos a granel -> 1 (el precio ya es el importe; con
     0 el artículo no sumaba en ningún total).
  3. precio guardado como total de la línea con cantidad > 1 -> precio
     unitario, cuando las propias notas dicen el unitario ("95.00 c/u",
     "$52.50/pza"): si un número X de las notas cumple X * cantidad = precio.
  4. Liga cada artículo con su sesión (campo nuevo `sesion`) cuando esa
     tienda y fecha tienen una sola sesión. Si hay dos sesiones el mismo día
     en la misma tienda no se adivina.
  5. Variantes de escritura del mismo nombre (solo mayúsculas/acentos) se
     unifican al nombre más usado.
  6. Siembra equivalencias/{tienda}/{TEXTO} y codigos/{ean} con lo que ya
     está en notas ("Ticket: MAN GALA", "Código 6584800002368").
  7. Días capturados dos veces (a mano, claves t0xxx, y en la importación
     t_1781590041567): se queda la importación solo si su suma da
     exactamente el total de las sesiones de ese día; la captura a mano de
     esos días trae el precio por kilo en lugar del importe.
  8. "Agua a granel" de Pachamama era el ticket cortado ("AGUA" a $75-105/kg):
     es aguacate.

Uso:
    python limpiar_historico.py            (modo prueba: muestra y no escribe)
    python limpiar_historico.py --aplicar  (respaldo + una sola escritura)

Todo se escribe en un solo PATCH a la raíz: o entra completo o no entra.
Lo que se cambió queda en mandadito-proceso/limpieza_{fecha}.json.
"""

import re
import sys
from collections import Counter, defaultdict
from datetime import datetime

from comun import (PROCESO, a_iso, clave_producto, clave_texto, get,
                   guardar_json, patch, respaldo)

LOTE_DUPLICADO = "t_1781590041567"
DUPLICADOS = [
    # (tienda, fecha, sesión que se borra)
    ("walmart", "01/06/2026", "s_1781590041567_3"),
    ("pachamama", "04/06/2026", "s_1781590041567_6"),
]


def numeros(texto):
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", (texto or "").replace(",", ""))]


def main():
    aplicar = "--aplicar" in sys.argv
    datos = get("")
    tickets = datos.get("tickets") or {}
    sesiones = datos.get("sesiones") or {}
    equivalencias = datos.get("equivalencias") or {}
    codigos = datos.get("codigos") or {}

    cambios = {}          # ruta -> valor nuevo (None = borrar)
    bitacora = defaultdict(list)

    # 1. Importación duplicada
    for tienda, fecha, ses in DUPLICADOS:
        for k, t in tickets.items():
            if k.startswith(LOTE_DUPLICADO + "_") and t["tienda"] == tienda and t["fecha"] == fecha:
                cambios[f"tickets/{k}"] = None
                bitacora["1_duplicado_borrado"].append({"key": k, **t})
        if ses in sesiones:
            cambios[f"sesiones/{ses}"] = None
            bitacora["1_duplicado_borrado"].append({"key": ses, **sesiones[ses]})

    vivos = {k: t for k, t in tickets.items() if f"tickets/{k}" not in cambios}
    vivas = {k: s for k, s in sesiones.items() if f"sesiones/{k}" not in cambios}

    # 2. cantidad 0
    for k, t in vivos.items():
        if not t.get("cantidad"):
            cambios[f"tickets/{k}/cantidad"] = 1
            bitacora["2_cantidad_0"].append(f"{k} {t['fecha']} {t['producto']}")

    # 3. precio de línea -> unitario
    for k, t in vivos.items():
        q, p = t.get("cantidad") or 1, t.get("precio") or 0
        if q <= 1:
            continue
        for x in numeros(t.get("notas")):
            if 0 < x < p and abs(x * q - p) < 0.05:
                cambios[f"tickets/{k}/precio"] = round(x, 2)
                bitacora["3_precio_unitario"].append(f"{k} {t['producto']}: {p} x{q} -> {x}")
                break

    # 4. Ligar artículo -> sesión
    por_dia = defaultdict(list)
    for sk, s in vivas.items():
        por_dia[(s["tienda"], s["fecha"])].append(sk)
    sin_liga = Counter()
    for k, t in vivos.items():
        if t.get("tipo") != "compra" or t.get("sesion"):
            continue
        cand = por_dia.get((t["tienda"], t["fecha"]), [])
        if len(cand) == 1:
            cambios[f"tickets/{k}/sesion"] = cand[0]
        else:
            sin_liga[(t["tienda"], t["fecha"], len(cand))] += 1
    bitacora["4_ligados"] = sum(1 for r in cambios if r.endswith("/sesion"))
    bitacora["4_sin_ligar"] = [f"{a} {b}: {n} artículos, {s} sesiones" for (a, b, s), n in sin_liga.items()]

    # 5. Variantes de escritura
    nombres = Counter(t["producto"] for t in vivos.values())
    for c in (datos.get("catalogo") or {}).values():
        nombres[c["producto"]] += 1
    grupos = defaultdict(list)
    for n in nombres:
        grupos[clave_producto(n)].append(n)
    canon = {}
    for variantes in grupos.values():
        if len(variantes) > 1:
            gana = max(variantes, key=lambda n: nombres[n])
            for v in variantes:
                if v != gana:
                    canon[v] = gana
    for nodo in ("tickets", "catalogo"):
        for k, r in (datos.get(nodo) or {}).items():
            if r["producto"] in canon and f"{nodo}/{k}" not in cambios:
                cambios[f"{nodo}/{k}/producto"] = canon[r["producto"]]
                bitacora["5_nombre_unificado"].append(f"{nodo}/{k}: {r['producto']} -> {canon[r['producto']]}")

    # 6. Sembrar equivalencias y códigos desde notas
    for k, t in vivos.items():
        nombre = canon.get(t["producto"], t["producto"])
        notas = t.get("notas") or ""
        m = re.search(r"Ticket:\s*([^·—|]+)", notas)
        if m:
            clave = clave_texto(m.group(1))
            if clave and clave not in (equivalencias.get(t["tienda"]) or {}):
                cambios[f"equivalencias/{t['tienda']}/{clave}"] = {
                    "producto": nombre, "veces": 1, "origen": "historico",
                    "actualizado": a_iso(t["fecha"]),
                }
                bitacora["6_equivalencias"].append(f"{t['tienda']} {clave} -> {nombre}")
        for ean in re.findall(r"C[oó]digo\s*(\d{8,14})", notas):
            if ean not in codigos:
                cambios[f"codigos/{ean}"] = {"producto": nombre, "tienda": t["tienda"], "origen": "historico"}
                bitacora["6_codigos"].append(f"{ean} -> {nombre}")

    # 7. Días capturados dos veces
    por_lote = defaultdict(lambda: defaultdict(list))
    for k, t in vivos.items():
        if t.get("tipo") == "compra" and f"tickets/{k}" not in cambios:
            lote = "manual" if k.startswith("t0") else k.rsplit("_", 1)[0]
            por_lote[(t["tienda"], t["fecha"])][lote].append(k)
    for (tienda, fecha), lotes in por_lote.items():
        if "manual" not in lotes or LOTE_DUPLICADO not in lotes:
            continue
        total_dia = sum(s["total"] for s in vivas.values() if s["tienda"] == tienda and s["fecha"] == fecha)
        suma_lote = sum(vivos[k]["precio"] * (vivos[k]["cantidad"] or 1) for k in lotes[LOTE_DUPLICADO])
        if total_dia and abs(suma_lote - total_dia) <= 0.05:
            for k in lotes["manual"]:
                cambios[f"tickets/{k}"] = None
                bitacora["7_dia_duplicado_borrado"].append({"key": k, **vivos[k]})

    # 8. "Agua a granel" -> aguacate
    for k, t in vivos.items():
        if t["producto"] == "Agua a granel" and f"tickets/{k}" not in cambios:
            cambios[f"tickets/{k}/producto"] = "Aguacate Hass a granel"
            cambios[f"tickets/{k}/categoria"] = "Frutas y Verduras"
            bitacora["8_agua_aguacate"].append(k)
    for k, c in (datos.get("catalogo") or {}).items():
        if c["producto"] == "Agua a granel":
            cambios[f"catalogo/{k}"] = None
            bitacora["8_agua_aguacate"].append(f"catalogo/{k}")

    # --- Reporte ---
    for nombre_regla, items in bitacora.items():
        if isinstance(items, list):
            print(f"\n[{nombre_regla}] {len(items)}")
            for it in items[:60]:
                print("   ", it if isinstance(it, str) else f"{it.get('key')} {it.get('producto', it.get('notas', ''))}")
        else:
            print(f"\n[{nombre_regla}] {items}")
    print(f"\nTotal de escrituras: {len(cambios)}")

    if not aplicar:
        print("\nMODO PRUEBA - no se escribió nada. Usa --aplicar.")
        return

    if not respaldo("antes_limpieza"):
        print("Respaldo fallido - cancelo.")
        sys.exit(1)
    patch("", cambios)
    ruta = PROCESO / f"limpieza_{datetime.now():%Y%m%d_%H%M%S}.json"
    guardar_json(ruta, {"cambios": cambios, "bitacora": bitacora})
    print(f"\nAplicado. Bitácora: {ruta}")


if __name__ == "__main__":
    main()
