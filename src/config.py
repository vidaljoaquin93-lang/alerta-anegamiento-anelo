"""
Configuración central del Sistema de Alerta Temprana de Anegamiento (Añelo).

Todos los parámetros calibrables viven acá. No hay valores mágicos dispersos
en el resto del código.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

# --------------------------------------------------------------------------- #
# Puntos geográficos críticos
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PuntoCritico:
    id: str
    nombre: str
    descripcion: str
    lat: float
    lon: float


PUNTOS: List[PuntoCritico] = [
    PuntoCritico(
        id="anelo_pueblo",
        nombre="Añelo Pueblo",
        descripcion="Base operativa",
        lat=-38.353,
        lon=-68.783,
    ),
    PuntoCritico(
        id="acceso_meseta",
        nombre="Acceso Meseta",
        descripcion="Ruta Prov. 17 / Bajada del Chañar",
        lat=-38.300,
        lon=-68.850,
    ),
    PuntoCritico(
        id="tratayen_sur",
        nombre="Tratayén / Sector Sur",
        descripcion="Acceso sur a yacimiento",
        lat=-38.483,
        lon=-68.500,
    ),
]

# --------------------------------------------------------------------------- #
# Zona horaria y ventanas de análisis
# --------------------------------------------------------------------------- #

TIMEZONE = "America/Argentina/Buenos_Aires"  # Argentina usa UTC-3 sin DST
PAST_DAYS = 3          # histórico reciente que pide Open-Meteo
FORECAST_DAYS = 3      # pronóstico a 72 h

VENTANA_ACUMULADO_H = 24    # lluvia caída en las últimas N horas
VENTANA_PRONOSTICO_H = 24   # lluvia pronosticada en las próximas N horas

# --------------------------------------------------------------------------- #
# Calibración de humedad de suelo
# --------------------------------------------------------------------------- #
# Open-Meteo devuelve `soil_moisture_0_to_7cm` en m³/m³ (contenido volumétrico),
# NO en porcentaje. La matriz de riesgo del proyecto está expresada en % de
# saturación, así que normalizamos contra la porosidad total del suelo.
#
#   saturacion_% = (soil_moisture / POROSIDAD_TOTAL) * 100
#
# VALOR ADOPTADO: 0.53 m³/m³, calibrado contra el backtest de 3 años de ERA5.
# Da ~16 días al año en nivel rojo, que es el orden de magnitud de cortes reales
# por barro en la zona. El valor teórico de porosidad para greda de meseta
# (0.42-0.48) producía 27-32 días/año: sobrealertaba, y un semáforo que está en
# rojo un mes seguido en invierno deja de ser mirado.
#
# Equivalencias con la matriz del proyecto (con 0.53):
#   60 % de saturación  ->  0.318 m³/m³
#   75 % de saturación  ->  0.398 m³/m³
#
# RECALIBRAR EN CAMPO: correr `python backtest.py --calibracion` y elegir la fila
# cuya frecuencia de días rojos coincida con lo que reporta vialidad.
POROSIDAD_TOTAL = float(os.getenv("IIE_POROSIDAD_TOTAL", "0.53"))

# --------------------------------------------------------------------------- #
# Umbrales de la matriz de riesgo (IIE)
# --------------------------------------------------------------------------- #

PRECIP_AMARILLO_MM = 3.0    # >= 3 mm  -> amarillo
PRECIP_ROJO_MM = 7.0        # >  7 mm  -> rojo

SATURACION_AMARILLO_PCT = 60.0   # >= 60 % -> amarillo
SATURACION_ROJO_PCT = 75.0       # >  75 % -> rojo

# Escalas para el índice continuo 0-100 (complemento al semáforo categórico)
IIE_PRECIP_SATURA_MM = 12.0      # 12 mm de lluvia = 100 puntos del subíndice
IIE_SUELO_PISO_PCT = 40.0        # por debajo de 40 % de saturación, subíndice 0
IIE_SUELO_TECHO_PCT = 85.0       # 85 % de saturación = 100 puntos del subíndice
IIE_PESO_PRECIP = 0.55
IIE_PESO_SUELO = 0.45

# Piso de IIE que impone una alerta SMN activa sobre la zona
IIE_PISO_SMN = {"amarillo": 50.0, "naranja": 75.0, "rojo": 90.0}

# --------------------------------------------------------------------------- #
# Fuentes de datos
# --------------------------------------------------------------------------- #

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Feed CAP oficial del SMN (Common Alerting Protocol, estándar OMM).
# Es público y NO requiere token, a diferencia de ws1.smn.gob.ar/v1/weather/alerts
# que hoy responde 401 Unauthorized sin JWT.
SMN_CAP_INDEX_URL = "https://ssl.smn.gob.ar/CAP/AR.php"

# Fallback opcional: API interna del SMN. Solo se usa si se carga el secret
# SMN_API_TOKEN en el repositorio. Si no existe, el sistema opera 100 % con CAP.
SMN_WS_URL = "https://ws1.smn.gob.ar/v1/weather/alerts"
SMN_API_TOKEN = os.getenv("SMN_API_TOKEN", "").strip()

# Eventos CAP que consideramos relevantes para anegamiento de caminos.
# El resto (viento, zonda, calor) se registra pero no eleva el semáforo.
EVENTOS_RELEVANTES = ("lluvia", "tormenta", "nevada", "precipitacion", "precipitación")

# Mapeo severidad CAP (OASIS) -> nomenclatura de colores del SMN
SEVERIDAD_CAP_A_COLOR = {
    "Minor": "amarillo",
    "Moderate": "amarillo",
    "Severe": "naranja",
    "Extreme": "rojo",
    "Unknown": "amarillo",
}

# Colores que, por sí solos, fuerzan nivel Rojo según la matriz del proyecto
COLORES_SMN_CRITICOS = ("naranja", "rojo")

# Margen de seguridad al testear si un punto cae dentro del polígono de un aviso.
# 0.02° ≈ 2,2 km. Cubre el caso de un punto justo sobre el borde de la grilla CAP
# y el hecho de que un camino a 2 km del límite está igual de afectado.
BUFFER_ALERTA_GRADOS = float(os.getenv("IIE_BUFFER_ALERTA", "0.02"))

# --------------------------------------------------------------------------- #
# Red / robustez
# --------------------------------------------------------------------------- #

HTTP_TIMEOUT = 30
HTTP_REINTENTOS = 3
HTTP_BACKOFF = 2.0          # segundos, se duplica en cada reintento
# El origen del SMN devuelve 522 si se lo satura: 4 conexiones es el punto
# estable observado en pruebas contra ssl.smn.gob.ar.
HTTP_MAX_WORKERS = 4        # descarga concurrente de XMLs CAP
USER_AGENT = "AlertaAnegamientoAnelo/1.0 (monitoreo vial; +github-actions)"

# --------------------------------------------------------------------------- #
# Persistencia
# --------------------------------------------------------------------------- #

DIR_DATOS = os.getenv("IIE_DIR_DATOS", "data")
CSV_HISTORICO = os.path.join(DIR_DATOS, "historico.csv")
JSON_ESTADO = os.path.join(DIR_DATOS, "estado_actual.json")
CSV_ALERTAS_SMN = os.path.join(DIR_DATOS, "alertas_smn.csv")
CSV_PRONOSTICO = os.path.join(DIR_DATOS, "pronostico_horario.csv")
DIR_DOCS = os.getenv("IIE_DIR_DOCS", "docs")
HTML_TABLERO = os.path.join(DIR_DOCS, "index.html")

RETENCION_DIAS_HISTORICO = int(os.getenv("IIE_RETENCION_DIAS", "400"))

# --------------------------------------------------------------------------- #
# Notificaciones (desactivadas por defecto)
# --------------------------------------------------------------------------- #
# Si el secret no está cargado, el módulo no notifica y NO falla la corrida.

TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Solo notificar a partir de este nivel
NIVEL_MINIMO_NOTIFICACION = os.getenv("IIE_NIVEL_NOTIFICACION", "amarillo").lower()

# Evita spam: solo notifica si el nivel CAMBIÓ respecto de la corrida anterior
NOTIFICAR_SOLO_CAMBIOS = os.getenv("IIE_NOTIFICAR_SOLO_CAMBIOS", "true").lower() == "true"

ORDEN_NIVELES = {"verde": 0, "amarillo": 1, "rojo": 2}

# Recomendación operativa por nivel (se usa en el tablero y las notificaciones)
ACCION_POR_NIVEL = {
    "verde": "Transitabilidad normal. Sin restricciones.",
    "amarillo": "Barro en greda. Circular solo con 4x4. Evitar equipos pesados sin escolta.",
    "rojo": "Anegamiento inminente / cortes de picadas. Suspender movimientos no críticos.",
}
