"""
subir.py - Paso 4 del pipeline: sube los tickets revisados a pipeline/pendientes

Toma revision.json (lo escribe revisar.py) y deja cada ticket en
pipeline/pendientes/{id} para revisarlo en la room Pendientes de la app
(Aprobar / Quitar). Nunca escribe en tickets/, sesiones/ ni catalogo/: eso
solo lo hace aplicar.py con lo que se aprobó.

Imágenes (pipeline/imagenes/{id}):
  - Se giran si el borrador trae `rotar` (grados contra reloj).
  - Las bandas de `ocultar` (medidas sobre la foto ya derecha) se tapan en
    negro ANTES de codificar: los datos de pago nunca salen de la laptop.
  - Lado largo de 1000 px, JPEG calidad 70.
  - La copia tapada queda en mandadito-proceso/subidas/ para revisarla a ojo.

Seguridad:
  - Modo prueba por defecto: sin --subir no escribe nada.
  - Idempotencia: subidos.json guarda los ids que ya se subieron.
  - No sube tickets con problemas de revisar.py (salvo --forzar).

Uso:
    python subir.py                (modo prueba; genera las imágenes tapadas)
    python subir.py --subir
"""

import base64
import io
import sys
from datetime import datetime

from PIL import Image, ImageDraw

from comun import PROCESO, cargar_json, guardar_json, put

REVISION = PROCESO / "revision.json"
SUBIDOS = PROCESO / "subidos.json"
REDUCIDAS = PROCESO / "reducidas"
SUBIDAS = PROCESO / "subidas"

LADO_MAX = 1000

CAMPOS_TICKET = ("tienda", "sucursal", "fecha", "hora", "subtotal", "total",
                 "ahorro", "articulos_impresos", "forma_pago", "suma",
                 "duplicadoDe", "reemplaza", "problemas", "avisos", "dudas", "fotos")
CAMPOS_ITEM = ("texto", "codigo", "cantidad", "importe", "descuento", "promo",
               "precio_unitario", "granel", "producto", "categoria", "subcategoria",
               "presentacion", "match", "confianza", "notas", "candidatos", "sugerido")


def id_firebase(id_):
    """Firebase no acepta . $ # [ ] / en claves; los paréntesis de "(0)" se quitan por limpieza."""
    return id_.replace("(", "").replace(")", "")


def imagen_tapada(foto, bandas, giro):
    with Image.open(REDUCIDAS / foto) as im:
        im = im.convert("RGB")
        if giro:
            # `rotar` va en grados contra reloj (como PIL); las bandas se
            # miden sobre la foto ya derecha, por eso se tapa después de girar.
            im = im.rotate(giro, expand=True)
        dibujo = ImageDraw.Draw(im)
        for y0, y1 in bandas or []:
            dibujo.rectangle([0, int(y0 * im.height), im.width, int(y1 * im.height)], fill="black")
        escala = LADO_MAX / max(im.size)
        if escala < 1:
            im = im.resize((round(im.width * escala), round(im.height * escala)), Image.LANCZOS)
        SUBIDAS.mkdir(parents=True, exist_ok=True)
        im.save(SUBIDAS / foto, "JPEG", quality=70)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=70)
        return base64.b64encode(buf.getvalue()).decode("ascii")


def sin_nulos(d):
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


def main():
    modo_subir = "--subir" in sys.argv
    forzar = "--forzar" in sys.argv
    revision = cargar_json(REVISION, None)
    if revision is None:
        print(f"Falta {REVISION}. Corre revisar.py primero.")
        sys.exit(1)
    subidos = cargar_json(SUBIDOS, {})

    if not modo_subir:
        print("MODO PRUEBA - no se escribe nada en Firebase. Usa --subir.\n")

    n_sub = n_ya = n_prob = 0
    for t in revision:
        id_ = id_firebase(t["id"])
        if id_ in subidos:
            n_ya += 1
            continue
        if t["problemas"] and not forzar:
            print(f"  [con problemas, no se sube] {id_}: {t['problemas'][0]}")
            n_prob += 1
            continue

        pendiente = sin_nulos({k: t.get(k) for k in CAMPOS_TICKET})
        pendiente["items"] = [sin_nulos({k: i.get(k) for k in CAMPOS_ITEM}) for i in t["items"]]
        pendiente["subido_en"] = datetime.now().isoformat(timespec="seconds")
        imagenes = [imagen_tapada(f, (t.get("ocultar") or {}).get(f), (t.get("rotar") or {}).get(f))
                    for f in t["fotos"]]
        kb = sum(len(i) for i in imagenes) * 3 // 4 // 1024

        marca = " [ya registrado]" if t.get("duplicadoDe") else ""
        resumen = f"{id_}  {t['tienda']} {t['fecha']} ${t['total']:,.2f} · {len(t['items'])} art. · {kb} KB{marca}"
        if not modo_subir:
            print(f"  [subiría] {resumen}")
            n_sub += 1
            continue

        put(f"pipeline/imagenes/{id_}", {"imagenes": imagenes})
        put(f"pipeline/pendientes/{id_}", pendiente)
        subidos[id_] = {"tienda": t["tienda"], "fecha": t["fecha"], "total": t["total"],
                        "subido_en": pendiente["subido_en"]}
        guardar_json(SUBIDOS, subidos)
        print(f"  [subido] {resumen}")
        n_sub += 1

    verbo = "Subidos" if modo_subir else "Subirían"
    print(f"\n{verbo}: {n_sub}   Ya subidos antes: {n_ya}   Con problemas: {n_prob}")
    print(f"Imágenes tapadas para revisar a ojo: {SUBIDAS}")


if __name__ == "__main__":
    main()
