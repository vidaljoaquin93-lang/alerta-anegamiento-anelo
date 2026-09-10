"""
Índice de Intransitabilidad por Estado del camino (IIE).

Dos salidas complementarias:

1. NIVEL CATEGÓRICO (semáforo) — es la regla autoritativa del proyecto:

   VERDE     Precipitación < 3 mm      Y  Saturación de suelo < 60 %
   AMARILLO  Precipitación 3 - 7 mm    O  Saturación de suelo 60 - 75 %
   ROJO      Precipitación > 7 mm      O  Saturación de suelo > 75 %
             O bien alerta SMN Naranja/Roja vigente sobre el punto

2. IIE CONTINUO 0-100 — índice numérico para tendencia y gauge en Power BI.
   No reemplaza al semáforo: lo acompaña.

Nota sobre la precipitación de referencia: la matriz habla de lluvia
"acumulada/pronosticada". Tomamos el MÁXIMO entre lo caído en las últimas 24 h
y lo pronosticado para las próximas 24 h, que es el criterio conservador para
una decisión logística (si ya llovió, el camino ya está comprometido; si va a
llover, hay que anticipar).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import config


# --------------------------------------------------------------------------- #
# Conversión de humedad de suelo
# --------------------------------------------------------------------------- #

def saturacion_pct(soil_moisture_m3m3: Optional[float]) -> Optional[float]:
    """
    Convierte el contenido volumétrico de agua (m³/m³) que devuelve Open-Meteo
    a porcentaje de saturación respecto de la porosidad total del suelo.
    """
    if soil_moisture_m3m3 is None:
        return None
    if config.POROSIDAD_TOTAL <= 0:
        return None
    return round(min(100.0, (soil_moisture_m3m3 / config.POROSIDAD_TOTAL) * 100.0), 1)


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


# --------------------------------------------------------------------------- #
# Nivel categórico
# --------------------------------------------------------------------------- #

def nivel_categorico(
    precip_mm: float,
    saturacion: Optional[float],
    color_smn: Optional[str] = None,
) -> Dict[str, Any]:
    """Aplica la matriz de riesgo. Devuelve el nivel y los disparadores."""
    disparadores: List[str] = []
    nivel = "verde"

    # --- Precipitación ---
    if precip_mm > config.PRECIP_ROJO_MM:
        nivel = "rojo"
        disparadores.append(f"Precipitación {precip_mm:.1f} mm (> {config.PRECIP_ROJO_MM:.0f} mm)")
    elif precip_mm >= config.PRECIP_AMARILLO_MM:
        nivel = "amarillo"
        disparadores.append(
            f"Precipitación {precip_mm:.1f} mm "
            f"({config.PRECIP_AMARILLO_MM:.0f}-{config.PRECIP_ROJO_MM:.0f} mm)"
        )

    # --- Humedad de suelo ---
    if saturacion is not None:
        if saturacion > config.SATURACION_ROJO_PCT:
            nivel = "rojo"
            disparadores.append(
                f"Saturación de suelo {saturacion:.0f} % (> {config.SATURACION_ROJO_PCT:.0f} %)"
            )
        elif saturacion >= config.SATURACION_AMARILLO_PCT:
            if nivel != "rojo":
                nivel = "amarillo"
            disparadores.append(
                f"Saturación de suelo {saturacion:.0f} % "
                f"({config.SATURACION_AMARILLO_PCT:.0f}-{config.SATURACION_ROJO_PCT:.0f} %)"
            )

    # --- Alerta oficial SMN ---
    if color_smn in config.COLORES_SMN_CRITICOS:
        nivel = "rojo"
        disparadores.append(f"Alerta SMN {color_smn.upper()} vigente sobre el punto")
    elif color_smn == "amarillo":
        if nivel == "verde":
            nivel = "amarillo"
        disparadores.append("Alerta SMN AMARILLA vigente sobre el punto")

    if not disparadores:
        disparadores.append("Sin disparadores. Condiciones normales.")

    return {"nivel": nivel, "disparadores": disparadores}


# --------------------------------------------------------------------------- #
# Índice continuo
# --------------------------------------------------------------------------- #

def iie_continuo(
    precip_mm: float,
    saturacion: Optional[float],
    color_smn: Optional[str] = None,
) -> Dict[str, float]:
    """Índice 0-100 ponderado, con piso impuesto por la alerta SMN."""
    sub_precip = _clamp(precip_mm / config.IIE_PRECIP_SATURA_MM * 100.0)

    if saturacion is None:
        sub_suelo = 0.0
        peso_precip, peso_suelo = 1.0, 0.0
    else:
        rango = config.IIE_SUELO_TECHO_PCT - config.IIE_SUELO_PISO_PCT
        sub_suelo = _clamp((saturacion - config.IIE_SUELO_PISO_PCT) / rango * 100.0)
        peso_precip, peso_suelo = config.IIE_PESO_PRECIP, config.IIE_PESO_SUELO

    indice = peso_precip * sub_precip + peso_suelo * sub_suelo

    if color_smn:
        indice = max(indice, config.IIE_PISO_SMN.get(color_smn, 0.0))

    return {
        "iie": round(_clamp(indice), 1),
        "subindice_precipitacion": round(sub_precip, 1),
        "subindice_suelo": round(sub_suelo, 1),
    }


# --------------------------------------------------------------------------- #
# Evaluación integral de un punto
# --------------------------------------------------------------------------- #

def evaluar_punto(
    clima: Dict[str, Any],
    alertas_smn: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Combina clima + alertas SMN y devuelve el registro completo del punto,
    listo para persistir y para el tablero.
    """
    from . import smn  # import local para evitar ciclo

    acum = float(clima.get("precip_acum_24h_mm") or 0.0)
    pron = float(clima.get("precip_pron_24h_mm") or 0.0)
    precip_ref = max(acum, pron)

    sat = saturacion_pct(clima.get("humedad_suelo_m3m3"))
    color = smn.peor_color(alertas_smn)

    cat = nivel_categorico(precip_ref, sat, color)
    cont = iie_continuo(precip_ref, sat, color)

    registro = {
        **{k: v for k, v in clima.items() if k != "serie_horaria"},
        "precip_referencia_mm": round(precip_ref, 2),
        "criterio_precip_referencia": "max(acumulado 24h, pronóstico 24h)",
        "saturacion_suelo_pct": sat,
        "porosidad_total_usada": config.POROSIDAD_TOTAL,
        "alerta_smn_color": color or "",
        "alerta_smn_cantidad": len(alertas_smn),
        "alerta_smn_eventos": "; ".join(
            sorted({a.get("evento", "") for a in alertas_smn if a.get("evento")})
        ),
        "nivel": cat["nivel"],
        "disparadores": cat["disparadores"],
        "accion_recomendada": config.ACCION_POR_NIVEL[cat["nivel"]],
        **cont,
        **perspectiva_72h(clima.get("serie_horaria", [])),
    }
    return registro


def perspectiva_72h(serie_horaria: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    La parte de "alerta TEMPRANA": recorre el pronóstico hora por hora,
    calcula el acumulado móvil de 24 h y devuelve el peor nivel que se
    alcanzaría y cuándo.

    Sin esto el sistema solo avisa cuando el camino ya se complicó.
    """
    futuras = [p for p in serie_horaria if p.get("es_pronostico")]
    if not futuras:
        return {"nivel_pronosticado": "verde", "pico_precip_24h_mm": 0.0,
                "hora_pico": None, "horas_hasta_pico": None}

    ventana: List[float] = []
    peor_nivel, peor_mm, peor_hora = "verde", 0.0, None

    for i, p in enumerate(futuras):
        ventana.append(float(p.get("precipitacion_mm") or 0.0))
        if len(ventana) > 24:
            ventana.pop(0)
        acum = sum(ventana)
        sat = saturacion_pct(p.get("humedad_suelo_m3m3"))
        nivel = nivel_categorico(acum, sat)["nivel"]
        if (config.ORDEN_NIVELES[nivel] > config.ORDEN_NIVELES[peor_nivel]
                or (nivel == peor_nivel and acum > peor_mm)):
            peor_nivel, peor_mm, peor_hora = nivel, acum, p["hora"]
            horas = i + 1

    return {
        "nivel_pronosticado": peor_nivel,
        "pico_precip_24h_mm": round(peor_mm, 1),
        "hora_pico": peor_hora,
        "horas_hasta_pico": (horas if peor_hora else None),
    }


def nivel_consolidado(registros: List[Dict[str, Any]]) -> str:
    """Peor nivel entre todos los puntos: es el estado del corredor completo."""
    if not registros:
        return "verde"
    return max(
        (r["nivel"] for r in registros),
        key=lambda n: config.ORDEN_NIVELES.get(n, 0),
    )
