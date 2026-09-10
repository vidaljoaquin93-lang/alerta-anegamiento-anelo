"""
Alertas oficiales del Servicio Meteorológico Nacional (SMN).

FUENTE PRIMARIA — Feed CAP (Common Alerting Protocol, estándar OASIS/OMM):
    https://ssl.smn.gob.ar/CAP/AR.php
Es público, no requiere autenticación y cada aviso trae el polígono geográfico
exacto de la zona afectada, lo que permite un test punto-en-polígono contra
nuestras coordenadas en lugar de un match difuso por nombre de provincia.

FUENTE SECUNDARIA (opcional) — API interna https://ws1.smn.gob.ar/v1/weather/alerts
Hoy responde 401 Unauthorized sin un JWT. Si en el futuro se consigue un token,
se carga como secret SMN_API_TOKEN y este módulo lo usa como complemento.
El sistema NO depende de ella.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from . import config
from .config import PuntoCritico
from .http_client import fetch, fetch_json

log = logging.getLogger(__name__)

NS = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}
RE_XML = re.compile(r"https://ssl\.smn\.gob\.ar/feeds/CAP/xml_generados/[^\"'\s]+\.xml")


# --------------------------------------------------------------------------- #
# Geometría
# --------------------------------------------------------------------------- #

def punto_en_poligono(lat: float, lon: float, poligono: List[Tuple[float, float]]) -> bool:
    """
    Ray casting (algoritmo de cruce par/impar).
    `poligono` es una lista de pares (lat, lon), como los entrega CAP.
    """
    if len(poligono) < 3:
        return False

    dentro = False
    n = len(poligono)
    j = n - 1
    for i in range(n):
        yi, xi = poligono[i]
        yj, xj = poligono[j]
        if (yi > lat) != (yj > lat):
            # abscisa del cruce del rayo horizontal con el segmento i-j
            x_cruce = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_cruce:
                dentro = not dentro
        j = i
    return dentro


def _parse_poligono(texto: str) -> List[Tuple[float, float]]:
    puntos: List[Tuple[float, float]] = []
    for par in texto.split():
        try:
            a, b = par.split(",")
            puntos.append((float(a), float(b)))
        except ValueError:
            continue
    return puntos


# --------------------------------------------------------------------------- #
# Descarga y parseo del feed CAP
# --------------------------------------------------------------------------- #

def _listar_xmls() -> List[str]:
    r = fetch(config.SMN_CAP_INDEX_URL)
    if r is None:
        log.error("No se pudo leer el índice CAP del SMN")
        return []
    urls = sorted(set(RE_XML.findall(r.text)))
    log.info("Índice CAP: %d avisos publicados", len(urls))
    return urls


def _parse_cap(xml_bytes: bytes, url: str) -> Optional[Dict[str, Any]]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        log.warning("XML CAP inválido (%s): %s", url, exc)
        return None

    def txt(elem, path: str, default: str = "") -> str:
        node = elem.find(path, NS)
        return (node.text or "").strip() if node is not None and node.text else default

    info = root.find("cap:info", NS)
    if info is None:
        return None

    severidad = txt(info, "cap:severity", "Unknown")
    poligonos: List[List[Tuple[float, float]]] = []
    areas: List[str] = []
    for area in info.findall("cap:area", NS):
        desc = txt(area, "cap:areaDesc")
        if desc:
            areas.append(desc)
        for pol in area.findall("cap:polygon", NS):
            if pol.text:
                p = _parse_poligono(pol.text)
                if p:
                    poligonos.append(p)

    return {
        "identificador": txt(root, "cap:identifier"),
        "estado": txt(root, "cap:status"),
        "tipo_mensaje": txt(root, "cap:msgType"),
        "emitido": txt(root, "cap:sent"),
        "evento": txt(info, "cap:event"),
        "severidad_cap": severidad,
        "color_smn": config.SEVERIDAD_CAP_A_COLOR.get(severidad, "amarillo"),
        "urgencia": txt(info, "cap:urgency"),
        "certeza": txt(info, "cap:certainty"),
        "inicio": txt(info, "cap:onset"),
        "expira": txt(info, "cap:expires"),
        "titulo": txt(info, "cap:headline"),
        "descripcion": txt(info, "cap:description"),
        "instruccion": txt(info, "cap:instruction"),
        "areas": areas,
        "poligonos": poligonos,
        "url": url,
    }


def _vigente(aviso: Dict[str, Any], ahora: datetime) -> bool:
    """Descarta avisos cancelados o ya expirados."""
    if aviso.get("estado", "").lower() not in ("actual", ""):
        return False
    if aviso.get("tipo_mensaje", "").lower() == "cancel":
        return False
    expira = aviso.get("expira") or ""
    if not expira:
        return True
    try:
        dt = datetime.fromisoformat(expira)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt >= ahora
    except ValueError:
        return True


def _relevante_para_anegamiento(aviso: Dict[str, Any]) -> bool:
    evento = (aviso.get("evento") or "").lower()
    return any(clave in evento for clave in config.EVENTOS_RELEVANTES)


def obtener_alertas(ahora: datetime) -> List[Dict[str, Any]]:
    """Descarga y parsea todos los avisos CAP vigentes del país."""
    urls = _listar_xmls()
    if not urls:
        return []

    def _bajar(u: str) -> Optional[Dict[str, Any]]:
        r = fetch(u, reintentos=3)
        return _parse_cap(r.content, u) if r is not None else None

    with ThreadPoolExecutor(max_workers=config.HTTP_MAX_WORKERS) as pool:
        crudos = list(pool.map(_bajar, urls))

    avisos = [a for a in crudos if a and _vigente(a, ahora)]
    log.info("Avisos CAP vigentes: %d de %d descargados", len(avisos), len(urls))
    return avisos


def _contiene_con_buffer(
    lat: float,
    lon: float,
    poligono: List[Tuple[float, float]],
    buffer_grados: float,
) -> bool:
    """
    Contención con margen de seguridad.

    Los polígonos CAP del SMN vienen en una grilla gruesa (~0.02°). Un punto que
    cae justo sobre el borde queda indefinido en el ray casting, y un camino a
    2 km del límite de un aviso está igual de afectado. Por eso, si el centro no
    da adentro, se prueban ocho puntos desplazados alrededor.

    Las cuatro diagonales importan: sobre un vértice del polígono, los cuatro
    desplazamientos en cruz pueden caer todos afuera según el ángulo del vértice,
    y el aviso se perdería. Verificado contra polígonos reales del SMN.
    """
    if punto_en_poligono(lat, lon, poligono):
        return True
    if buffer_grados <= 0:
        return False

    d = buffer_grados
    g = d * 0.7071  # componente de las diagonales, para igual distancia radial
    desplazamientos = (
        (d, 0.0), (-d, 0.0), (0.0, d), (0.0, -d),
        (g, g), (g, -g), (-g, g), (-g, -g),
    )
    return any(
        punto_en_poligono(lat + dy, lon + dx, poligono)
        for dy, dx in desplazamientos
    )


def alertas_para_punto(
    punto: PuntoCritico,
    avisos: List[Dict[str, Any]],
    buffer_grados: float = config.BUFFER_ALERTA_GRADOS,
) -> List[Dict[str, Any]]:
    """Filtra los avisos cuyo polígono contiene (o casi) el punto crítico."""
    coincidencias = []
    for aviso in avisos:
        if any(
            _contiene_con_buffer(punto.lat, punto.lon, p, buffer_grados)
            for p in aviso["poligonos"]
        ):
            coincidencias.append(aviso)
    return coincidencias


def peor_color(avisos: List[Dict[str, Any]], solo_relevantes: bool = True) -> Optional[str]:
    """Devuelve el color SMN más severo entre los avisos dados."""
    orden = {"amarillo": 1, "naranja": 2, "rojo": 3}
    candidatos = [a for a in avisos if not solo_relevantes or _relevante_para_anegamiento(a)]
    if not candidatos:
        return None
    return max((a["color_smn"] for a in candidatos), key=lambda c: orden.get(c, 0))


# --------------------------------------------------------------------------- #
# Fuente secundaria opcional (requiere token)
# --------------------------------------------------------------------------- #

def obtener_alertas_ws() -> List[Dict[str, Any]]:
    """
    Consulta la API interna del SMN si hay token cargado.
    Silenciosamente devuelve [] si no hay secret configurado.
    """
    if not config.SMN_API_TOKEN:
        return []

    data = fetch_json(
        config.SMN_WS_URL,
        headers={"Authorization": f"JWT {config.SMN_API_TOKEN}"},
    )
    if not isinstance(data, list):
        log.warning("SMN ws1 no devolvió una lista de alertas")
        return []

    log.info("SMN ws1: %d alertas recuperadas con token", len(data))
    return data
