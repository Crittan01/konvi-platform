import re
import unicodedata

# Diccionario ordenado por longitud DESCENDENTE de claves para evitar conflictos.
# e.g., procesar "avenida carrera" antes que "avenida" o "carrera".
DIAN_DICT = {
    "vias de nombre comun": "NOMBRE VIA",
    "avenida carrera": "AK",
    "avenida calle": "AC",
    "centro comercial": "CC",
    "conjunto residencial": "CON",
    "inspeccion departamental": "IPD",
    "inspeccion municipal": "IPM",
    "inspeccion de policia": "IP",
    "local mezzanine": "LM",
    "super manzana": "SM",
    "unidad residencial": "UR",
    "zona franca": "ZF",
    "administracion": "AD",
    "aeropuerto": "AER",
    "agrupacion": "AGP",
    "apartamento": "AP",
    "apartado": "APTDO",
    "autopista": "AUT",
    "anillo vial": "AVIAL",
    "boulevard": "BLV",
    "carretera": "CRT",
    "circunvalar": "CRV",
    "consultorio": "CS",
    "departamento": "DPTO",
    "deposito sotano": "DS",
    "escalera": "ES",
    "glorieta": "GT",
    "hacienda": "HC",
    "kilometro": "KM",
    "mezzanine": "MN",
    "occidente": "OCC",
    "parcela": "PA",
    "penthouse": "PH",
    "porteria": "POR",
    "parqueadero": "PQ",
    "round point": "RP",
    "salon comunal": "SC",
    "semisotano": "SS",
    "terraplen": "TERPLN",
    "transversal": "TV",
    "urbanizacion": "URB",
    "variante": "VTE",
    "adelante": "ADL",
    "almacen": "ALM",
    "altillo": "AL",
    "al lado": "ALD",
    "agencia": "AG",
    "avenida": "AV",
    "atras": "ATR",
    "barrio": "BRR",
    "bodega": "BG",
    "bloque": "BL",
    "camino": "CN",
    "caserio": "CAS",
    "circular": "CIR",
    "ciudadela": "CD",
    "conjunto": "CONJ",
    "corregimiento": "C",
    "carrera": "CR",
    "cra": "CR",
    "celula": "CEL",
    "centro": "CEN",
    "callejon": "CLJ",
    "calle": "CL",
    "casa": "CA",
    "deposito": "DP",
    "diagonal": "DG",
    "diag": "DG",
    "edificio": "ED",
    "entrada": "EN",
    "esquina": "ESQ",
    "exterior": "EX",
    "etapa": "ET",
    "finca": "FCA",
    "garaje": "GJ",
    "hangar": "HG",
    "interior": "IN",
    "local": "LC",
    "lote": "LT",
    "manzana": "MZ",
    "modulo": "MD",
    "muelle": "MLL",
    "mojon": "MJ",
    "norte": "NORTE",
    "oriente": "O",
    "oeste": "OESTE",
    "oficina": "OF",
    "parque": "PAR",
    "pasaje": "PJ",
    "planta": "PL",
    "predio": "PD",
    "paseo": "PS",
    "puente": "PN",
    "puesto": "PT",
    "poste": "POS",
    "paraje": "PRJ",
    "piso": "P",
    "salida": "SD",
    "sector": "SEC",
    "sotano": "ST",
    "solar": "SL",
    "salon": "SA",
    "suite": "SUITE",
    "sur": "SUR",
    "terminal": "TER",
    "terraza": "TZ",
    "torre": "TO",
    "unidad": "UN",
    "vereda": "VRD",
    "zona": "ZN",
    "este": "ESTE",
    "apto": "AP",
    "ed": "ED",
    "av": "AV",
}

_PATTERNS = []
# Pre-compile the pattern checks bounding to \b (word boundaries) to avoid replacing word substrings
for word, replacement in DIAN_DICT.items():
    pattern = re.compile(rf"\b{word}\b", flags=re.IGNORECASE)
    _PATTERNS.append((pattern, replacement))

def normalize_dian_address(address: str) -> str:
    """
    Toma una dirección natural (Avenida Carrera 68c # 22-10 sur) y la 
    devuelve en la nomenclatura de la DIAN formateada (AK 68C 22-10 SUR)
    """
    if not address:
        return ""
        
    # 1. Remover acentos (tilde/diéresis) para match preciso
    addr = ''.join(c for c in unicodedata.normalize('NFD', address) if unicodedata.category(c) != 'Mn')
    
    # 2. Remover `#`, `,` y `.` para flujo limpio, transformarlo en espacio.
    addr = re.sub(r'[#,\.]', ' ', addr)
    addr = re.sub(r'\s+', ' ', addr).strip()
    
    # 3. Aplicar diccionario normalizador capa por capa
    for pattern, replacement in _PATTERNS:
        addr = pattern.sub(replacement, addr)
        
    # 4. Formatear y eliminar posibles dobles espacios sueltos
    return re.sub(r'\s+', ' ', addr).strip().upper()
