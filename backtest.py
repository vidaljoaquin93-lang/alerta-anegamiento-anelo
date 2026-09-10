#!/usr/bin/env python3
"""
Backtest de la matriz de riesgo contra el histórico real (ERA5 / Open-Meteo Archive).

Responde la pregunta que va a hacer el gerente: "¿esto habría detectado los
eventos que efectivamente cortaron los caminos?".

Reproduce hora por hora el cálculo del semáforo sobre datos observados de los
últimos N años y reporta:
  - cuántas horas habría estado en cada nivel
  - los episodios rojos/amarillos más severos, con fecha y lluvia acumulada

Uso:
    python backtest.py                          # últimos 3 años, todos los puntos
    python backtest.py --desde 2024-01-01 --hasta 2024-12-31
    python backtest.py --punto anelo_pueblo --csv backtest.csv
"""

from __future__ import annotations

import argparse
import csv
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from src import config, iie
from src.http_client import fetch_json

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
log = logging.getLogger("backtest")

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def descargar(lat: float, lon: float, desde: str, hasta: str) -> Optional[Dict[str, Any]]:
    return fetch_json(ARCHIVE_URL, params={
        "latitude": lat, "longitude": lon,
        "start_date": desde, "end_date": hasta,
        "hourly": "precipitation,soil_moisture_0_to_7cm",
        "timezone": config.TIMEZONE,
    }, timeout=90)


def replay(punto, desde: str, hasta: str) -> List[Dict[str, Any]]:
    """Recalcula el semáforo para cada hora del período."""
    data = descargar(punto.lat, punto.lon, desde, hasta)
    if not data or "hourly" not in data:
        log.error("Sin datos de archivo para %s", punto.nombre)
        return []

    h = data["hourly"]
    tiempos = [datetime.fromisoformat(t) for t in h["time"]]
    precip = [v if v is not None else 0.0 for v in h["precipitation"]]
    suelo = h["soil_moisture_0_to_7cm"]

    filas: List[Dict[str, Any]] = []
    for i in range(len(tiempos)):
        # Acumulado de las últimas 24 h. En backtest no hay pronóstico, así que
        # la lluvia de referencia es solo el acumulado observado: es el criterio
        # MÁS EXIGENTE para el sistema (no puede anticipar, solo reaccionar).
        acum = round(sum(precip[max(0, i - 23):i + 1]), 2)
        sat = iie.saturacion_pct(suelo[i]) if i < len(suelo) else None
        cat = iie.nivel_categorico(acum, sat)
        cont = iie.iie_continuo(acum, sat)
        filas.append({
            "punto_id": punto.id,
            "punto_nombre": punto.nombre,
            "hora": tiempos[i].isoformat(timespec="hours"),
            "precip_1h_mm": precip[i],
            "precip_acum_24h_mm": acum,
            "humedad_suelo_m3m3": suelo[i] if i < len(suelo) else None,
            "saturacion_suelo_pct": sat,
            "nivel": cat["nivel"],
            "iie": cont["iie"],
            "disparadores": " | ".join(cat["disparadores"]),
        })
    return filas


def episodios(filas: List[Dict[str, Any]], nivel_min: str = "amarillo") -> List[Dict[str, Any]]:
    """Agrupa horas consecutivas en el mismo nivel (o superior) en episodios."""
    umbral = config.ORDEN_NIVELES[nivel_min]
    eps: List[Dict[str, Any]] = []
    actual: Optional[Dict[str, Any]] = None

    for f in filas:
        activo = config.ORDEN_NIVELES.get(f["nivel"], 0) >= umbral
        if activo:
            if actual is None:
                actual = {
                    "punto": f["punto_nombre"], "inicio": f["hora"], "fin": f["hora"],
                    "horas": 0, "peor_nivel": f["nivel"],
                    "max_precip_24h": f["precip_acum_24h_mm"],
                    "max_saturacion": f["saturacion_suelo_pct"] or 0,
                    "max_iie": f["iie"],
                }
            actual["fin"] = f["hora"]
            actual["horas"] += 1
            if config.ORDEN_NIVELES[f["nivel"]] > config.ORDEN_NIVELES[actual["peor_nivel"]]:
                actual["peor_nivel"] = f["nivel"]
            actual["max_precip_24h"] = max(actual["max_precip_24h"], f["precip_acum_24h_mm"])
            actual["max_saturacion"] = max(actual["max_saturacion"], f["saturacion_suelo_pct"] or 0)
            actual["max_iie"] = max(actual["max_iie"], f["iie"])
        elif actual is not None:
            eps.append(actual)
            actual = None

    if actual is not None:
        eps.append(actual)
    return eps


def tabla_calibracion(filas: List[Dict[str, Any]]) -> None:
    """
    Sensibilidad del semáforo al único parámetro subjetivo del modelo:
    la porosidad total del suelo usada para pasar de m³/m³ a % de saturación.

    Es la tabla de decisión: se elige el valor cuya frecuencia de días
    restringidos coincida con lo que el equipo de vialidad observa en campo.
    """
    sm = [float(f["humedad_suelo_m3m3"]) for f in filas if f["humedad_suelo_m3m3"] is not None]
    if not sm:
        return
    precip = [float(f["precip_acum_24h_mm"]) for f in filas]
    n = len(filas)

    print("=" * 78)
    print("SENSIBILIDAD A LA CALIBRACIÓN DE POROSIDAD (parámetro POROSIDAD_TOTAL)")
    print("=" * 78)
    print(f"  {'porosidad':>10}{'umbral 60%':>12}{'umbral 75%':>12}"
          f"{'% h amarillo':>14}{'% h rojo':>11}{'días rojo/año':>15}")

    for por in (0.42, 0.45, 0.48, 0.50, 0.53, 0.56):
        u_am, u_ro = 0.60 * por, 0.75 * por
        amar = rojo = 0
        for f, p in zip(filas, precip):
            s = f["humedad_suelo_m3m3"]
            es_rojo = p > config.PRECIP_ROJO_MM or (s is not None and s > u_ro)
            es_amar = (config.PRECIP_AMARILLO_MM <= p <= config.PRECIP_ROJO_MM
                       or (s is not None and u_am <= s <= u_ro))
            if es_rojo:
                rojo += 1
            elif es_amar:
                amar += 1
        marca = "  <- actual" if abs(por - config.POROSIDAD_TOTAL) < 1e-9 else ""
        print(f"  {por:>10.2f}{u_am:>12.3f}{u_ro:>12.3f}"
              f"{amar/n*100:>13.1f}%{rojo/n*100:>10.1f}%"
              f"{rojo/n*365:>14.0f}{marca}")

    print("\n  Distribución observada de humedad de suelo 0-7 cm (m³/m³):")
    orden = sorted(sm)
    for etiqueta, q in (("mediana", 0.50), ("p75", 0.75), ("p90", 0.90),
                        ("p95", 0.95), ("p98", 0.98), ("máximo", 1.0)):
        print(f"    {etiqueta:<9} {orden[min(len(orden) - 1, int(q * len(orden)))]:.3f}")
    print()


def main() -> int:
    hoy = date.today()
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", default=(hoy - timedelta(days=365 * 3)).isoformat())
    ap.add_argument("--hasta", default=(hoy - timedelta(days=6)).isoformat())
    ap.add_argument("--punto", default=None, help="id de un punto específico")
    ap.add_argument("--csv", default=None, help="volcar el detalle horario a CSV")
    ap.add_argument("--calibracion", action="store_true",
                    help="tabla de sensibilidad a la porosidad del suelo")
    args = ap.parse_args()

    puntos = [p for p in config.PUNTOS if args.punto is None or p.id == args.punto]
    todas: List[Dict[str, Any]] = []

    print(f"\nBACKTEST DE LA MATRIZ IIE — {args.desde} a {args.hasta}")
    print("Fuente: reanálisis ERA5 vía Open-Meteo Archive (datos observados)\n")

    for punto in puntos:
        filas = replay(punto, args.desde, args.hasta)
        if not filas:
            continue
        todas += filas

        total = len(filas)
        cuenta = {n: sum(1 for f in filas if f["nivel"] == n) for n in ("verde", "amarillo", "rojo")}
        eps = episodios(filas)
        rojos = [e for e in eps if e["peor_nivel"] == "rojo"]

        print("=" * 78)
        print(f"{punto.nombre}  ({punto.lat}, {punto.lon})")
        print("=" * 78)
        print(f"  Horas analizadas: {total:,}")
        for n in ("verde", "amarillo", "rojo"):
            print(f"    {n.upper():9} {cuenta[n]:6,} h   {cuenta[n]/total*100:5.1f} %")
        print(f"  Episodios con restricción (amarillo o peor): {len(eps)}")
        print(f"    de los cuales llegaron a ROJO: {len(rojos)}")

        top = sorted(eps, key=lambda e: (-e["max_iie"], -e["horas"]))[:5]
        if top:
            print("\n  Episodios más severos:")
            print(f"    {'inicio':<14}{'dur.':>6}{'nivel':>10}{'lluvia 24h':>12}{'suelo':>8}{'IIE':>7}")
            for e in top:
                print(f"    {e['inicio'][:13]:<14}{e['horas']:>4} h{e['peor_nivel'].upper():>10}"
                      f"{e['max_precip_24h']:>10.1f} mm{e['max_saturacion']:>7.0f}%{e['max_iie']:>7.0f}")
        print()

        if args.calibracion:
            tabla_calibracion(filas)

    if args.csv and todas:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(todas[0].keys()))
            w.writeheader()
            w.writerows(todas)
        print(f"Detalle horario -> {args.csv} ({len(todas):,} filas)\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
