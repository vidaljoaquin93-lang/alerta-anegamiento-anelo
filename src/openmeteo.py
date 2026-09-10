"""
Ingesta de variables climáticas desde Open-Meteo (API gratuita, sin API key).

Para cada punto crítico devuelve:
  - lluvia acumulada en las últimas N horas (dato observado/reanálisis)
  - lluvia pronosticada para las próximas N horas
  - humedad volumétrica del suelo 0-7 cm en el instante actual
  - serie horaria completa (para el gráfico del tablero)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from . import config
from .config import PuntoCritico
from .http_client import fetch_json

log = logging.getLogger(__name__)

VARIABLES_HORARIAS = [
    "precipitation",
    "rain",
    "soil_moisture_0_to_7cm",
    "temperature_2m",
    "wind_speed_10m",
]


def _parse_hora(t: str) -> datetime:
    return datetime.fromisoformat(t)


def _suma_ventana(
    tiempos: List[datetime],
    valores: List[Optional[float]],
    desde: datetime,
    hasta: datetime,
) -> float:
    """Suma los valores cuya marca temporal cae en [desde, hasta)."""
    total = 0.0
    for t, v in zip(tiempos, valores):
        if desde <= t < hasta and v is not None:
            total += float(v)
    return round(total, 2)


def _valor_mas_cercano(
    tiempos: List[datetime],
    valores: List[Optional[float]],
    objetivo: datetime,
) -> Optional[float]:
    """Valor de la serie en la hora más próxima a `objetivo`."""
    mejor: Optional[float] = None
    mejor_delta: Optional[timedelta] = None
    for t, v in zip(tiempos, valores):
        if v is None:
            continue
        delta = abs(t - objetivo)
        if mejor_delta is None or delta < mejor_delta:
            mejor, mejor_delta = float(v), delta
    return mejor


def obtener_clima(punto: PuntoCritico, ahora: datetime) -> Optional[Dict[str, Any]]:
    """
    Consulta Open-Meteo para un punto. Devuelve None si la API no responde,
    para que el orquestador pueda decidir (degradar a último dato conocido).
    """
    params = {
        "latitude": punto.lat,
        "longitude": punto.lon,
        "hourly": ",".join(VARIABLES_HORARIAS),
        "past_days": config.PAST_DAYS,
        "forecast_days": config.FORECAST_DAYS,
        "timezone": config.TIMEZONE,
    }

    data = fetch_json(config.OPEN_METEO_URL, params=params)
    if not data or "hourly" not in data:
        log.error("Open-Meteo sin datos para %s", punto.nombre)
        return None

    h = data["hourly"]
    try:
        tiempos = [_parse_hora(t) for t in h["time"]]
    except (KeyError, ValueError) as exc:
        log.error("Serie horaria inválida para %s: %s", punto.nombre, exc)
        return None

    precipitacion = h.get("precipitation") or []
    lluvia = h.get("rain") or []
    suelo = h.get("soil_moisture_0_to_7cm") or []
    temp = h.get("temperature_2m") or []
    viento = h.get("wind_speed_10m") or []

    # `ahora` viene en hora local Argentina y sin tzinfo, igual que la serie.
    hora_actual = ahora.replace(minute=0, second=0, microsecond=0)

    acum = _suma_ventana(
        tiempos, precipitacion,
        hora_actual - timedelta(hours=config.VENTANA_ACUMULADO_H),
        hora_actual + timedelta(hours=1),
    )
    pron_24 = _suma_ventana(
        tiempos, precipitacion,
        hora_actual + timedelta(hours=1),
        hora_actual + timedelta(hours=config.VENTANA_PRONOSTICO_H + 1),
    )
    pron_72 = _suma_ventana(
        tiempos, precipitacion,
        hora_actual + timedelta(hours=1),
        hora_actual + timedelta(hours=73),
    )
    acum_72 = _suma_ventana(
        tiempos, precipitacion,
        hora_actual - timedelta(hours=72),
        hora_actual + timedelta(hours=1),
    )

    sm_actual = _valor_mas_cercano(tiempos, suelo, hora_actual)
    sm_max_72 = max((v for v in suelo if v is not None), default=None)

    serie = [
        {
            "hora": t.isoformat(timespec="minutes"),
            "precipitacion_mm": (precipitacion[i] if i < len(precipitacion) else None),
            "humedad_suelo_m3m3": (suelo[i] if i < len(suelo) else None),
            "temperatura_c": (temp[i] if i < len(temp) else None),
            "viento_kmh": (viento[i] if i < len(viento) else None),
            "es_pronostico": t > hora_actual,
        }
        for i, t in enumerate(tiempos)
    ]

    return {
        "punto_id": punto.id,
        "punto_nombre": punto.nombre,
        "lat": punto.lat,
        "lon": punto.lon,
        "elevacion_m": data.get("elevation"),
        "precip_acum_24h_mm": acum,
        "precip_acum_72h_mm": acum_72,
        "precip_pron_24h_mm": pron_24,
        "precip_pron_72h_mm": pron_72,
        "humedad_suelo_m3m3": sm_actual,
        "humedad_suelo_max_periodo_m3m3": sm_max_72,
        "lluvia_actual_mm": _valor_mas_cercano(tiempos, lluvia, hora_actual),
        "temperatura_c": _valor_mas_cercano(tiempos, temp, hora_actual),
        "viento_kmh": _valor_mas_cercano(tiempos, viento, hora_actual),
        "serie_horaria": serie,
    }
