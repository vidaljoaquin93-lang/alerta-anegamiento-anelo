"""
Persistencia. Estrategia por defecto: CSV + JSON versionados en el propio
repositorio (costo cero, sin credenciales). Power BI se conecta a la URL raw
de GitHub con el conector Web.

El módulo de Google Sheets queda escrito y desactivado: se activa solo si el
secret GOOGLE_SHEETS_CREDENTIALS existe.
"""

from __future__ import annotations

import csv
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from . import config

log = logging.getLogger(__name__)

COLUMNAS_HISTORICO = [
    "timestamp_local",
    "fecha",
    "hora",
    "punto_id",
    "punto_codigo",
    "punto_nombre",
    "lat",
    "lon",
    "nivel",
    "iie",
    "precip_referencia_mm",
    "precip_acum_24h_mm",
    "precip_acum_72h_mm",
    "precip_pron_24h_mm",
    "precip_pron_72h_mm",
    "humedad_suelo_m3m3",
    "saturacion_suelo_pct",
    "subindice_precipitacion",
    "subindice_suelo",
    "temperatura_c",
    "viento_kmh",
    "alerta_smn_color",
    "alerta_smn_cantidad",
    "alerta_smn_eventos",
    "disparadores",
    "accion_recomendada",
]

COLUMNAS_ALERTAS = [
    "timestamp_local",
    "punto_id",
    "punto_nombre",
    "identificador",
    "evento",
    "severidad_cap",
    "color_smn",
    "urgencia",
    "certeza",
    "inicio",
    "expira",
    "titulo",
    "descripcion",
    "url",
]

COLUMNAS_PRONOSTICO = [
    "punto_id",
    "punto_nombre",
    "hora",
    "precipitacion_mm",
    "humedad_suelo_m3m3",
    "saturacion_suelo_pct",
    "temperatura_c",
    "viento_kmh",
    "es_pronostico",
]


def _asegurar_dir(ruta: str) -> None:
    d = os.path.dirname(ruta)
    if d:
        os.makedirs(d, exist_ok=True)


# --------------------------------------------------------------------------- #
# Histórico (append-only, con poda por retención)
# --------------------------------------------------------------------------- #

def _fila_historico(reg: Dict[str, Any], ts: datetime) -> Dict[str, Any]:
    return {
        "timestamp_local": ts.isoformat(timespec="seconds"),
        "fecha": ts.date().isoformat(),
        "hora": ts.strftime("%H:%M"),
        "punto_id": reg.get("punto_id"),
        "punto_codigo": reg.get("punto_codigo"),
        "punto_nombre": reg.get("punto_nombre"),
        "lat": reg.get("lat"),
        "lon": reg.get("lon"),
        "nivel": reg.get("nivel"),
        "iie": reg.get("iie"),
        "precip_referencia_mm": reg.get("precip_referencia_mm"),
        "precip_acum_24h_mm": reg.get("precip_acum_24h_mm"),
        "precip_acum_72h_mm": reg.get("precip_acum_72h_mm"),
        "precip_pron_24h_mm": reg.get("precip_pron_24h_mm"),
        "precip_pron_72h_mm": reg.get("precip_pron_72h_mm"),
        "humedad_suelo_m3m3": reg.get("humedad_suelo_m3m3"),
        "saturacion_suelo_pct": reg.get("saturacion_suelo_pct"),
        "subindice_precipitacion": reg.get("subindice_precipitacion"),
        "subindice_suelo": reg.get("subindice_suelo"),
        "temperatura_c": reg.get("temperatura_c"),
        "viento_kmh": reg.get("viento_kmh"),
        "alerta_smn_color": reg.get("alerta_smn_color"),
        "alerta_smn_cantidad": reg.get("alerta_smn_cantidad"),
        "alerta_smn_eventos": reg.get("alerta_smn_eventos"),
        "disparadores": " | ".join(reg.get("disparadores", [])),
        "accion_recomendada": reg.get("accion_recomendada"),
    }


def append_historico(registros: List[Dict[str, Any]], ts: datetime) -> None:
    _asegurar_dir(config.CSV_HISTORICO)
    existe = os.path.exists(config.CSV_HISTORICO)
    with open(config.CSV_HISTORICO, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS_HISTORICO)
        if not existe:
            w.writeheader()
        for reg in registros:
            w.writerow(_fila_historico(reg, ts))
    log.info("Histórico: +%d filas -> %s", len(registros), config.CSV_HISTORICO)


def podar_historico(ahora: datetime) -> None:
    """Mantiene el CSV acotado para que el repo no crezca sin control."""
    if not os.path.exists(config.CSV_HISTORICO):
        return
    corte = ahora - timedelta(days=config.RETENCION_DIAS_HISTORICO)
    with open(config.CSV_HISTORICO, newline="", encoding="utf-8") as f:
        filas = list(csv.DictReader(f))

    conservadas = []
    for fila in filas:
        try:
            if datetime.fromisoformat(fila["timestamp_local"]) >= corte:
                conservadas.append(fila)
        except (ValueError, KeyError):
            conservadas.append(fila)

    if len(conservadas) != len(filas):
        with open(config.CSV_HISTORICO, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNAS_HISTORICO)
            w.writeheader()
            w.writerows(conservadas)
        log.info("Histórico podado: %d filas eliminadas", len(filas) - len(conservadas))


def leer_estado_anterior() -> Optional[Dict[str, Any]]:
    if not os.path.exists(config.JSON_ESTADO):
        return None
    try:
        with open(config.JSON_ESTADO, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        log.warning("No se pudo leer el estado anterior: %s", exc)
        return None


# --------------------------------------------------------------------------- #
# Estado actual y tablas auxiliares
# --------------------------------------------------------------------------- #

def guardar_estado(estado: Dict[str, Any]) -> None:
    _asegurar_dir(config.JSON_ESTADO)
    with open(config.JSON_ESTADO, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)
    log.info("Estado actual -> %s", config.JSON_ESTADO)


def guardar_alertas(alertas_por_punto: Dict[str, List[Dict[str, Any]]],
                    nombres: Dict[str, str], ts: datetime) -> None:
    _asegurar_dir(config.CSV_ALERTAS_SMN)
    with open(config.CSV_ALERTAS_SMN, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS_ALERTAS)
        w.writeheader()
        for punto_id, alertas in alertas_por_punto.items():
            for a in alertas:
                w.writerow({
                    "timestamp_local": ts.isoformat(timespec="seconds"),
                    "punto_id": punto_id,
                    "punto_nombre": nombres.get(punto_id, ""),
                    "identificador": a.get("identificador"),
                    "evento": a.get("evento"),
                    "severidad_cap": a.get("severidad_cap"),
                    "color_smn": a.get("color_smn"),
                    "urgencia": a.get("urgencia"),
                    "certeza": a.get("certeza"),
                    "inicio": a.get("inicio"),
                    "expira": a.get("expira"),
                    "titulo": a.get("titulo"),
                    "descripcion": (a.get("descripcion") or "").replace("\n", " "),
                    "url": a.get("url"),
                })


def guardar_pronostico(series: Dict[str, Dict[str, Any]]) -> None:
    """Serie horaria de todos los puntos, para el gráfico de Power BI."""
    from .iie import saturacion_pct

    _asegurar_dir(config.CSV_PRONOSTICO)
    with open(config.CSV_PRONOSTICO, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS_PRONOSTICO)
        w.writeheader()
        for punto_id, datos in series.items():
            for p in datos.get("serie_horaria", []):
                w.writerow({
                    "punto_id": punto_id,
                    "punto_nombre": datos.get("punto_nombre"),
                    "hora": p["hora"],
                    "precipitacion_mm": p["precipitacion_mm"],
                    "humedad_suelo_m3m3": p["humedad_suelo_m3m3"],
                    "saturacion_suelo_pct": saturacion_pct(p["humedad_suelo_m3m3"]),
                    "temperatura_c": p["temperatura_c"],
                    "viento_kmh": p["viento_kmh"],
                    "es_pronostico": p["es_pronostico"],
                })


# --------------------------------------------------------------------------- #
# Google Sheets — OPCIONAL, desactivado si no hay credenciales
# --------------------------------------------------------------------------- #

def sincronizar_google_sheets(registros: List[Dict[str, Any]], ts: datetime) -> bool:
    """
    Escribe el histórico en una hoja de Google. Requiere:
      - secret GOOGLE_SHEETS_CREDENTIALS (JSON del service account)
      - variable GOOGLE_SHEETS_ID (id del spreadsheet, compartido con el
        e-mail del service account con permiso de edición)
      - `pip install gspread google-auth`

    Devuelve False y NO falla si no está configurado.
    """
    creds_json = os.getenv("GOOGLE_SHEETS_CREDENTIALS", "").strip()
    sheet_id = os.getenv("GOOGLE_SHEETS_ID", "").strip()
    if not creds_json or not sheet_id:
        log.debug("Google Sheets no configurado; se omite.")
        return False

    try:
        import gspread                                  # type: ignore
        from google.oauth2.service_account import Credentials  # type: ignore
    except ImportError:
        log.warning("gspread/google-auth no instalados; se omite Google Sheets.")
        return False

    try:
        creds = Credentials.from_service_account_info(
            json.loads(creds_json),
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        hoja = gspread.authorize(creds).open_by_key(sheet_id).sheet1

        if not hoja.get_all_values():
            hoja.append_row(COLUMNAS_HISTORICO)

        filas = [
            [_fila_historico(r, ts).get(c, "") for c in COLUMNAS_HISTORICO]
            for r in registros
        ]
        hoja.append_rows(filas, value_input_option="USER_ENTERED")
        log.info("Google Sheets: %d filas escritas", len(filas))
        return True
    except Exception as exc:  # noqa: BLE001 - nunca debe tumbar la corrida
        log.error("Google Sheets falló (se continúa con CSV): %s", exc)
        return False
