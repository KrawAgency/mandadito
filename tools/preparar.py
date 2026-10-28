"""
preparar.py - Paso 1 del pipeline de tickets

Detecta fotos nuevas en la carpeta de Drive, las endereza (EXIF), las reduce
y las agrupa en tickets probables. Escribe el manifiesto que usa la
extracción.

  - Orientación: ImageOps.exif_transpose ANTES de reducir (lección de
    NutriLog: sin esto el 96 % de las fotos llegaban giradas).
  - Tamaño: lado largo de 1568 px, el máximo que la extracción ve sin que
    se vuelva a reducir; los tickets son letra chica.
  - Copias exactas (mismo contenido, p. ej. "foto(0).jpg"): se marcan y no
    se extraen dos veces.
  - Grupos: fotos tomadas con menos de GRUPO_MIN minutos de diferencia se
    proponen como un mismo ticket (un ticket largo se fotografía en
    partes). Es solo una propuesta: la extracción la confirma o la parte.
  - La fecha del EXIF solo sirve para agrupar y ordenar. La fecha que vale
    es la impresa en el ticket.

Uso:
    python preparar.py
    python preparar.py --todo     (vuelve a procesar aunque ya estén en
                                   procesadas.json)
"""

import hashlib
import sys
from datetime import datetime

from PIL import Image, ImageOps

from comun import ENTRADA, PROCESO, cargar_json, guardar_json

REDUCIDAS = PROCESO / "reducidas"
MANIFIESTO = PROCESO / "manifiesto.json"
REGISTRO = PROCESO / "procesadas.json"

LADO_MAX = 1568
GRUPO_MIN = 3
EXTENSIONES = {".jpg", ".jpeg", ".png"}


def leer_fecha_exif(ruta):
    try:
        with Image.open(ruta) as im:
            exif = im.getexif()
            crudo = exif.get(36867) or exif.get(306)
            if not crudo:
                crudo = exif.get_ifd(0x8769).get(36867)
            if crudo:
                return datetime.strptime(crudo, "%Y:%m:%d %H:%M:%S"), "exif"
    except Exception:
        pass
    return datetime.fromtimestamp(ruta.stat().st_mtime), "archivo"


def reducir(origen, destino):
    with Image.open(origen) as im:
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
        escala = LADO_MAX / max(im.size)
        if escala < 1:
            im = im.resize((round(im.width * escala), round(im.height * escala)), Image.LANCZOS)
        im.save(destino, "JPEG", quality=88)
        return im.size


def huella(ruta):
    return hashlib.sha1(ruta.read_bytes()).hexdigest()


def main():
    if not ENTRADA.exists():
        print(f"No existe la carpeta de entrada: {ENTRADA}")
        sys.exit(1)
    REDUCIDAS.mkdir(parents=True, exist_ok=True)

    procesadas = {} if "--todo" in sys.argv else cargar_json(REGISTRO, {})
    fotos = sorted(p for p in ENTRADA.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONES)
    nuevas = [p for p in fotos if p.name not in procesadas]
    if not nuevas:
        print(f"Sin fotos nuevas. Ya procesadas: {len(procesadas)}")
        return
    print(f"Fotos nuevas: {len(nuevas)}\n")

    vistas = {v["huella"]: k for k, v in procesadas.items() if isinstance(v, dict)}
    entradas = []
    for foto in nuevas:
        if foto.stat().st_size == 0:
            print(f"  [omitida] {foto.name} pesa 0 bytes (¿Drive no terminó de bajarla?)")
            continue
        h = huella(foto)
        if h in vistas:
            print(f"  [copia] {foto.name} es idéntica a {vistas[h]}")
            procesadas[foto.name] = {"huella": h, "copia_de": vistas[h]}
            continue
        vistas[h] = foto.name
        cuando, fuente = leer_fecha_exif(foto)
        destino = REDUCIDAS / f"{foto.stem}.jpg"
        try:
            ancho, alto = reducir(foto, destino)
        except Exception as e:
            print(f"  [error] {foto.name}: {e}")
            continue
        entradas.append({
            "archivo": foto.name,
            "reducida": str(destino),
            "tomada": cuando.isoformat(timespec="seconds"),
            "fuente_fecha": fuente,
            "tamano": [ancho, alto],
            "huella": h,
        })

    # Agrupar por cercanía en el tiempo
    entradas.sort(key=lambda e: e["tomada"])
    grupo, anterior = None, None
    for e in entradas:
        t = datetime.fromisoformat(e["tomada"])
        if anterior is None or (t - anterior).total_seconds() > GRUPO_MIN * 60:
            grupo = e["archivo"].rsplit(".", 1)[0]
        e["grupo"] = grupo
        anterior = t

    manifiesto = cargar_json(MANIFIESTO, [])
    ya = {m["archivo"] for m in manifiesto}
    manifiesto += [e for e in entradas if e["archivo"] not in ya]
    manifiesto.sort(key=lambda e: e["tomada"])
    guardar_json(MANIFIESTO, manifiesto)
    for e in entradas:
        procesadas[e["archivo"]] = {"huella": e["huella"], "grupo": e["grupo"]}
    guardar_json(REGISTRO, procesadas)

    grupos = {}
    for e in entradas:
        grupos.setdefault(e["grupo"], []).append(e["archivo"])
    for g, fs in grupos.items():
        print(f"  {g}: {len(fs)} foto(s)")
    print(f"\nListas: {len(entradas)} fotos en {len(grupos)} grupos")
    print(f"Manifiesto: {MANIFIESTO}")


if __name__ == "__main__":
    main()
