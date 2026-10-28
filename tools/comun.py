"""
comun.py - Piezas compartidas del pipeline de Mandadito

Configuración, acceso a Firebase por REST, respaldo, fechas y normalización
de texto. Solo librería estándar (Pillow solo lo usa preparar.py).
"""

import json
import re
import unicodedata
import urllib.request
from datetime import datetime
from pathlib import Path

# --- Configuracion -----------------------------------------------------------

BASE_URL = "https://compras-visor-default-rtdb.firebaseio.com"
ENTRADA = Path(r"C:\GoogleDrive\Tickets-compras")
PROCESO = Path(r"C:\dev\mandadito-proceso")
RESPALDOS = PROCESO / "respaldos"

# Misma lista que CONFIG_TIENDAS en index.html, más las que ya existen en datos.
TIENDAS = {
    "costco": ("Costco", "Cancún"),
    "walmart": ("Walmart", "Cancún"),
    "chedraui": ("Chedraui", "Cancún"),
    "chedpm": ("Chedraui P.M.", "Puerto Morelos"),
    "aki": ("Super Aki", "Puerto Morelos"),
    "ml": ("MercadoLibre", "Cancún"),
    "pachamama": ("Pachamama P.M.", "Puerto Morelos"),
    "oceanleader": ("Ocean Leader", "Cancún"),
    "multiproteinas": ("Multiproteínas", "Cancún"),
    "aurrera": ("Bodega Aurrera", "Puerto Morelos"),
    "similares": ("Farmacias Similares", "Puerto Morelos"),
    "delsol": ("Tiendas Del Sol", "Cancún"),
    "oxxo": ("Oxxo", "Puerto Morelos"),
    "gomart": ("GoMart", "Cancún"),
    "velvet": ("Papelería Velvet", "Puerto Morelos"),
}

# Nodos de datos "de verdad" (los que lee la app). pipeline/ no cuenta.
NODOS_DATOS = ("tickets", "catalogo", "sesiones", "codigos", "equivalencias")


# --- Firebase ----------------------------------------------------------------


def _pedir(metodo, ruta, valor=None):
    url = f"{BASE_URL}/{ruta}.json"
    data = None
    headers = {}
    if valor is not None:
        data = json.dumps(valor, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=metodo, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        cuerpo = r.read().decode("utf-8")
    return json.loads(cuerpo) if cuerpo else None


def get(ruta):
    return _pedir("GET", ruta)


def put(ruta, valor):
    return _pedir("PUT", ruta, valor)


def patch(ruta, valor):
    """Escritura múltiple en una sola llamada: {"a/b": 1, "c": null, ...}."""
    return _pedir("PATCH", ruta, valor)


def delete(ruta):
    return _pedir("DELETE", ruta)


def respaldo(etiqueta="respaldo"):
    """
    Baja la base completa a respaldos/{etiqueta}_{fecha}.json.
    Devuelve la ruta, o None si falló (quien llama debe cancelar).
    """
    RESPALDOS.mkdir(parents=True, exist_ok=True)
    try:
        datos = get("")
    except Exception as e:
        print(f"  [error] respaldo: {e}")
        return None
    if not datos or "tickets" not in datos:
        print("  [error] respaldo vacío o sin tickets/")
        return None
    ruta = RESPALDOS / f"{etiqueta}_{datetime.now():%Y%m%d_%H%M%S}.json"
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    print(f"  respaldo: {ruta}")
    return ruta


# --- Fechas ------------------------------------------------------------------
# Firebase guarda "DD/MM/AAAA" (así lo escribe la app). Para comparar y ordenar
# se usa ISO "AAAA-MM-DD".


def a_iso(fecha):
    if not fecha:
        return ""
    fecha = str(fecha).strip()
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", fecha)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", fecha)
    if m:
        return fecha
    return ""


def a_firebase(fecha_iso):
    a, m, d = fecha_iso.split("-")
    return f"{d}/{m}/{a}"


# --- Texto -------------------------------------------------------------------


def sin_acentos(s):
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def clave_texto(s):
    """
    Clave para la tabla de equivalencias: mayúsculas, sin acentos, sin
    signos, espacios simples. "Lch Desl. 1L" -> "LCH DESL 1L".
    Firebase no acepta . $ # [ ] / en claves, por eso se quitan.
    """
    s = sin_acentos(str(s or "")).upper()
    s = re.sub(r"[^A-Z0-9 %]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def clave_producto(s):
    """Clave para comparar nombres canónicos entre sí (detectar duplicados)."""
    return clave_texto(s).lower()


def cargar_json(ruta, defecto):
    ruta = Path(ruta)
    if ruta.exists():
        return json.loads(ruta.read_text(encoding="utf-8"))
    return defecto


def guardar_json(ruta, datos):
    Path(ruta).write_text(
        json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8"
    )
