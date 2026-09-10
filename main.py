#!/usr/bin/env python3
"""
Sistema de Alerta Temprana de Anegamiento de Caminos — Añelo, Vaca Muerta.

Orquestador. Diseñado para correr en GitHub Actions cada 2 horas con costo
cero de infraestructura.

Flujo:
    1. Descarga alertas CAP vigentes del SMN (una sola vez para todo el país).
    2. Para cada punto crítico: consulta Open-Meteo y filtra las alertas SMN
       cuyo polígono contiene el punto.
    3. Calcula el nivel del semáforo y el IIE 0-100.
    4. Persiste histórico (CSV), estado actual (JSON) y tablas auxiliares.
    5. Regenera el tablero HTML estático (GitHub Pages).
    6. Notifica si corresponde (Teams/Telegram, si hay secrets).

Uso:
    python main.py                 # corrida normal
    python main.py --dry-run       # no escribe archivos ni notifica
    python main.py --sin-red       # usa el último estado guardado (debug)
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from src import config, dashboard, iie, notifier, openmeteo, smn, storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)-22s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

# Argentina: UTC-3 todo el año
TZ_AR = timezone(timedelta(hours=-3))


def ahora_local() -> datetime:
    """Hora local Argentina, sin tzinfo (para comparar con las series de Open-Meteo)."""
    return datetime.now(TZ_AR).replace(tzinfo=None)


def ejecutar(dry_run: bool = False) -> Dict[str, Any]:
    ts = ahora_local()
    log.info("=" * 70)
    log.info("Corrida %s (hora local Argentina)", ts.isoformat(timespec="seconds"))
    log.info("=" * 70)

    # ---- 1. Alertas oficiales SMN (feed CAP público) ---------------------- #
    try:
        avisos = smn.obtener_alertas(ts)
    except Exception as exc:  # noqa: BLE001
        log.error("Fallo inesperado leyendo el SMN: %s", exc)
        avisos = []

    avisos_ws = smn.obtener_alertas_ws()  # solo si hay token; [] si no
    if avisos_ws:
        log.info("Fuente secundaria SMN ws1 activa (%d registros)", len(avisos_ws))

    # ---- 2 y 3. Clima + evaluación por punto ------------------------------ #
    registros: List[Dict[str, Any]] = []
    series: Dict[str, Dict[str, Any]] = {}
    alertas_por_punto: Dict[str, List[Dict[str, Any]]] = {}
    puntos_con_error: List[str] = []

    for punto in config.PUNTOS:
        log.info("--- %s (%s, %s) ---", punto.nombre, punto.lat, punto.lon)
        clima = openmeteo.obtener_clima(punto, ts)
        if clima is None:
            puntos_con_error.append(punto.nombre)
            log.error("Sin datos climáticos para %s. Se omite del cálculo.", punto.nombre)
            continue

        alertas = smn.alertas_para_punto(punto, avisos)
        alertas_por_punto[punto.id] = alertas
        series[punto.id] = clima

        reg = iie.evaluar_punto(clima, alertas)
        registros.append(reg)

        log.info(
            "  nivel=%s  IIE=%s  lluvia_ref=%.1f mm  suelo=%s%%  SMN=%s",
            reg["nivel"].upper(), reg["iie"], reg["precip_referencia_mm"],
            reg["saturacion_suelo_pct"], reg["alerta_smn_color"] or "sin alerta",
        )
        for d in reg["disparadores"]:
            log.info("    · %s", d)

    if not registros:
        log.error("Ningún punto pudo evaluarse. Se aborta sin escribir.")
        raise SystemExit(1)

    # ---- 4. Estado consolidado ------------------------------------------- #
    consolidado = iie.nivel_consolidado(registros)
    estado_anterior = storage.leer_estado_anterior()

    estado: Dict[str, Any] = {
        "timestamp_local": ts.isoformat(timespec="seconds"),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "zona": "Añelo — Vaca Muerta (Neuquén)",
        "nivel_consolidado": consolidado,
        "iie_maximo": max(r["iie"] for r in registros),
        "accion_recomendada": config.ACCION_POR_NIVEL[consolidado],
        "puntos": registros,
        "alertas_smn_vigentes_zona": [
            {k: v for k, v in a.items() if k != "poligonos"}
            for a in {
                a["identificador"]: a
                for lista in alertas_por_punto.values() for a in lista
            }.values()
        ],
        "avisos_cap_pais": len(avisos),
        "puntos_con_error": puntos_con_error,
        "parametros": {
            "porosidad_total_m3m3": config.POROSIDAD_TOTAL,
            "precip_amarillo_mm": config.PRECIP_AMARILLO_MM,
            "precip_rojo_mm": config.PRECIP_ROJO_MM,
            "saturacion_amarillo_pct": config.SATURACION_AMARILLO_PCT,
            "saturacion_rojo_pct": config.SATURACION_ROJO_PCT,
            "ventana_acumulado_h": config.VENTANA_ACUMULADO_H,
            "ventana_pronostico_h": config.VENTANA_PRONOSTICO_H,
        },
        "nivel_anterior": (estado_anterior or {}).get("nivel_consolidado"),
    }

    log.info("=" * 70)
    log.info("NIVEL CONSOLIDADO DEL CORREDOR: %s", consolidado.upper())
    log.info("%s", config.ACCION_POR_NIVEL[consolidado])
    log.info("=" * 70)

    if dry_run:
        log.info("--dry-run: no se escriben archivos ni se notifica.")
        log.info("\n%s", notifier.previsualizar(estado))
        return estado

    # ---- 5. Persistencia -------------------------------------------------- #
    nombres = {p.id: p.nombre for p in config.PUNTOS}
    storage.append_historico(registros, ts)
    storage.podar_historico(ts)
    storage.guardar_alertas(alertas_por_punto, nombres, ts)
    storage.guardar_pronostico(series)
    storage.sincronizar_google_sheets(registros, ts)  # no-op si no hay secret

    # ---- 6. Tablero estático --------------------------------------------- #
    try:
        dashboard.generar(estado, series, avisos)
    except Exception as exc:  # noqa: BLE001
        log.error("No se pudo generar el tablero HTML: %s", exc)

    # El estado se guarda al final: así `nivel_anterior` de la próxima corrida
    # refleja realmente la corrida previa completa.
    if notifier.debe_notificar(consolidado, estado_anterior):
        estado["notificado_a"] = notifier.notificar(estado)
    else:
        log.info("Sin cambio de nivel o bajo umbral: no se notifica.")
        estado["notificado_a"] = []

    storage.guardar_estado(estado)
    return estado


def main() -> int:
    ap = argparse.ArgumentParser(description="Alerta temprana de anegamiento — Añelo")
    ap.add_argument("--dry-run", action="store_true",
                    help="Ejecuta el cálculo sin escribir archivos ni notificar")
    args = ap.parse_args()

    try:
        ejecutar(dry_run=args.dry_run)
        return 0
    except SystemExit as exc:
        return int(exc.code or 1)
    except Exception as exc:  # noqa: BLE001
        log.exception("Fallo no controlado: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
