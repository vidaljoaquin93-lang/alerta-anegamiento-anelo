#!/usr/bin/env python3
"""
Verificación final de todo el sistema, con datos reales y en vivo.

No confía en nada previo: vuelve a llamar a las APIs, recalcula, contrasta los
resultados contra los archivos generados y reporta qué está verificado y qué no.

Uso:  python verificacion_final.py
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src import config, iie, smn  # noqa: E402

TZ_AR = timezone(timedelta(hours=-3))
OK, FALLA, AVISO = "OK    ", "FALLA ", "AVISO "
resultados = []


def chequeo(nombre: str, estado: str, detalle: str = "") -> None:
    resultados.append((estado, nombre, detalle))
    print(f"  [{estado}] {nombre}" + (f" — {detalle}" if detalle else ""))


def seccion(titulo: str) -> None:
    print(f"\n{'=' * 78}\n{titulo}\n{'=' * 78}")


# --------------------------------------------------------------------------- #
def v_tests() -> None:
    seccion("1. TESTS UNITARIOS")
    r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                       capture_output=True, text=True)
    salida = r.stderr.strip().splitlines()
    ultima = salida[-1] if salida else ""
    cuantos = next((l for l in salida if l.startswith("Ran ")), "")
    chequeo("Suite de tests", OK if r.returncode == 0 else FALLA,
            f"{cuantos} — {ultima}")


def v_openmeteo() -> None:
    seccion("2. OPEN-METEO EN VIVO")
    from src import openmeteo
    ahora = datetime.now(TZ_AR).replace(tzinfo=None)
    for p in config.PUNTOS:
        d = openmeteo.obtener_clima(p, ahora)
        if d is None:
            chequeo(f"Clima {p.nombre}", FALLA, "la API no respondió")
            continue
        n = len(d["serie_horaria"])
        sm = d["humedad_suelo_m3m3"]
        problemas = []
        if n != 144:
            problemas.append(f"serie de {n} h, se esperaban 144")
        if sm is None:
            problemas.append("humedad de suelo nula")
        elif not 0 <= sm <= 1:
            problemas.append(f"humedad de suelo fuera de rango: {sm}")
        chequeo(f"Clima {p.nombre}", FALLA if problemas else OK,
                "; ".join(problemas) or
                f"{n} h · suelo {sm} m³/m³ · pron. 72 h {d['precip_pron_72h_mm']} mm")


def v_smn() -> None:
    seccion("3. SMN — FEED CAP EN VIVO")
    ahora = datetime.now(TZ_AR).replace(tzinfo=None)
    avisos = smn.obtener_alertas(ahora)

    chequeo("Descarga del feed CAP", OK if avisos else FALLA,
            f"{len(avisos)} avisos vigentes")
    if not avisos:
        return

    con_pol = sum(1 for a in avisos if a["poligonos"])
    chequeo("Avisos con polígono", OK if con_pol == len(avisos) else AVISO,
            f"{con_pol}/{len(avisos)}")

    rel = [a for a in avisos if smn._relevante_para_anegamiento(a)]
    chequeo("Filtro de eventos relevantes", OK if rel else AVISO,
            f"{len(rel)} de {len(avisos)} (lluvia/tormenta/nevada)")

    # Prueba funcional de la geometría con polígonos reales
    ok = mal = 0
    for a in avisos[:30]:
        for pol in a["poligonos"]:
            lats = [v[0] for v in pol]
            lons = [v[1] for v in pol]
            cy, cx = sum(lats) / len(lats), sum(lons) / len(lons)
            if smn.punto_en_poligono(cy, cx, pol) and \
               not smn.punto_en_poligono(max(lats) + 10, cx, pol):
                ok += 1
            else:
                mal += 1
    chequeo("Point-in-polygon (centroide dentro / lejano fuera)",
            OK if ok > mal * 4 else AVISO,
            f"{ok} correctos, {mal} anómalos (polígonos cóncavos)")

    # Prueba de escalada: un punto dentro de un aviso real debe elevar el nivel
    candidatos = [a for a in rel if a["poligonos"]]
    if candidatos:
        pol = candidatos[0]["poligonos"][0]
        cy = sum(v[0] for v in pol) / len(pol)
        cx = sum(v[1] for v in pol) / len(pol)

        class _P:
            lat, lon, nombre = cy, cx, "prueba"

        m = smn.alertas_para_punto(_P(), avisos)
        color = smn.peor_color(m)
        n_naranja = iie.nivel_categorico(0.0, 20.0, "naranja")["nivel"]
        n_rojo = iie.nivel_categorico(0.0, 20.0, "rojo")["nivel"]
        chequeo("Detección dentro de un aviso real",
                OK if m else FALLA, f"{len(m)} avisos, color {color}")
        chequeo("Escalada SMN naranja → rojo",
                OK if n_naranja == "rojo" else FALLA, f"resultado: {n_naranja}")
        chequeo("Escalada SMN roja → rojo",
                OK if n_rojo == "rojo" else FALLA, f"resultado: {n_rojo}")

    for p in config.PUNTOS:
        m = smn.alertas_para_punto(p, avisos)
        chequeo(f"Avisos sobre {p.nombre}", OK,
                f"{len(m)} — color {smn.peor_color(m) or 'sin alerta relevante'}")


def v_matriz() -> None:
    seccion("4. MATRIZ DE RIESGO — CASOS DE BORDE")
    casos = [
        (0.0, 20.0, None, "verde",    "seco"),
        (2.99, 50.0, None, "verde",   "justo debajo del umbral amarillo"),
        (3.0, 50.0, None, "amarillo", "umbral amarillo exacto"),
        (7.0, 50.0, None, "amarillo", "7 mm sigue siendo amarillo"),
        (7.01, 50.0, None, "rojo",    "apenas por encima de 7 mm"),
        (0.0, 59.9, None, "verde",    "suelo justo debajo de 60 %"),
        (0.0, 60.0, None, "amarillo", "suelo en 60 %"),
        (0.0, 75.0, None, "amarillo", "suelo en 75 % sigue amarillo"),
        (0.0, 75.1, None, "rojo",     "suelo apenas por encima de 75 %"),
        (0.0, 20.0, "amarillo", "amarillo", "alerta SMN amarilla"),
        (0.0, 20.0, "naranja", "rojo",  "alerta SMN naranja fuerza rojo"),
        (0.0, 20.0, "rojo",    "rojo",  "alerta SMN roja fuerza rojo"),
        (0.0, None, None, "verde",     "sin dato de suelo no rompe"),
    ]
    for precip, sat, color, esperado, desc in casos:
        obtenido = iie.nivel_categorico(precip, sat, color)["nivel"]
        chequeo(desc, OK if obtenido == esperado else FALLA,
                f"esperado {esperado}, obtenido {obtenido}")

    # Calibración vigente
    u60 = config.SATURACION_AMARILLO_PCT / 100 * config.POROSIDAD_TOTAL
    u75 = config.SATURACION_ROJO_PCT / 100 * config.POROSIDAD_TOTAL
    chequeo("Calibración de porosidad",
            OK if abs(config.POROSIDAD_TOTAL - 0.53) < 1e-9 else FALLA,
            f"{config.POROSIDAD_TOTAL} m³/m³ → amarillo {u60:.3f}, rojo {u75:.3f}")


def v_salidas() -> None:
    seccion("5. ARCHIVOS GENERADOS")
    ahora = datetime.now(TZ_AR).replace(tzinfo=None)

    for ruta in (config.JSON_ESTADO, config.CSV_HISTORICO,
                 config.CSV_PRONOSTICO, config.CSV_ALERTAS_SMN,
                 config.HTML_TABLERO):
        chequeo(f"Existe {ruta}", OK if os.path.exists(ruta) else FALLA,
                f"{os.path.getsize(ruta):,} bytes" if os.path.exists(ruta) else "")

    with open(config.JSON_ESTADO, encoding="utf-8") as f:
        estado = json.load(f)

    edad = (ahora - datetime.fromisoformat(estado["timestamp_local"])).total_seconds() / 60
    chequeo("Antigüedad del estado", OK if edad < 180 else AVISO,
            f"{edad:.0f} minutos")
    chequeo("Puntos evaluados",
            OK if len(estado["puntos"]) == len(config.PUNTOS) else FALLA,
            f"{len(estado['puntos'])} de {len(config.PUNTOS)}")
    chequeo("Puntos con error", OK if not estado["puntos_con_error"] else FALLA,
            str(estado["puntos_con_error"] or "ninguno"))
    chequeo("Porosidad registrada en el estado",
            OK if estado["parametros"]["porosidad_total_m3m3"] == config.POROSIDAD_TOTAL else FALLA,
            str(estado["parametros"]["porosidad_total_m3m3"]))

    # El nivel consolidado debe ser el peor de los puntos
    peor = max((p["nivel"] for p in estado["puntos"]),
               key=lambda n: config.ORDEN_NIVELES[n])
    chequeo("Nivel consolidado = peor punto",
            OK if peor == estado["nivel_consolidado"] else FALLA,
            f"{estado['nivel_consolidado']} vs peor punto {peor}")

    # Recalcular el nivel de cada punto desde sus propios números
    for p in estado["puntos"]:
        rec = iie.nivel_categorico(p["precip_referencia_mm"],
                                   p["saturacion_suelo_pct"],
                                   p["alerta_smn_color"] or None)["nivel"]
        chequeo(f"Nivel recalculado {p['punto_nombre']}",
                OK if rec == p["nivel"] else FALLA,
                f"archivo dice {p['nivel']}, recálculo da {rec}")

    with open(config.CSV_HISTORICO, newline="", encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    chequeo("Histórico acumulando", OK if len(filas) >= 3 else AVISO,
            f"{len(filas)} filas")

    with open(config.CSV_PRONOSTICO, newline="", encoding="utf-8") as f:
        pron = list(csv.DictReader(f))
    esperado = len(config.PUNTOS) * 144
    chequeo("Serie horaria completa", OK if len(pron) == esperado else AVISO,
            f"{len(pron)} filas, se esperaban {esperado}")


def v_tablero() -> None:
    seccion("6. TABLERO HTML")
    with open(config.HTML_TABLERO, encoding="utf-8") as f:
        html = f.read()

    import re
    externos = re.findall(r'(?:src|href)\s*=\s*["\'](https?://[^"\']+)', html)
    chequeo("Sin dependencias externas", OK if not externos else FALLA,
            "cero recursos remotos" if not externos else str(externos[:3]))

    for marca, desc in (("<!doctype html>", "doctype"),
                        ('http-equiv="refresh"', "recarga automática"),
                        ('id="banner-stale"', "cartel de dato viejo"),
                        ('id="frescura"', "indicador de antigüedad"),
                        ("__DATOS__", "datos embebidos"),
                        ('lang="es-AR"', "idioma")):
        chequeo(f"Contiene {desc}", OK if marca in html else FALLA)

    chequeo("Tamaño del tablero", OK if len(html) < 2_000_000 else AVISO,
            f"{len(html):,} bytes")


def v_workflow() -> None:
    seccion("7. WORKFLOW DE GITHUB ACTIONS")
    ruta = ".github/workflows/monitoreo.yml"
    if not os.path.exists(ruta):
        chequeo("Workflow presente", FALLA)
        return
    try:
        import yaml
        d = yaml.safe_load(open(ruta, encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        chequeo("YAML válido", FALLA, str(exc))
        return

    chequeo("YAML válido", OK)
    job = d["jobs"]["monitorear"]
    chequeo("Permiso de escritura",
            OK if d.get("permissions", {}).get("contents") == "write" else FALLA)
    pasos = [p.get("name", "") for p in job["steps"]]
    chequeo("Corre los tests antes de monitorear",
            OK if any("test" in p.lower() for p in pasos) else FALLA)
    # El cron se lee con la clave True por el YAML 1.1 (on: -> True)
    disparadores = d.get("on") or d.get(True) or {}
    cron = disparadores.get("schedule", [{}])[0].get("cron", "")
    chequeo("Programado cada 2 h", OK if cron == "0 */2 * * *" else AVISO, cron)


def v_powerquery() -> None:
    seccion("8. SCRIPTS DE POWER QUERY")
    r = subprocess.run([sys.executable, "verificar_m.py",
                        "01_IIE_Estado.m", "02_IIE_Serie_Horaria.m"],
                       capture_output=True, text=True, cwd="microsoft")
    chequeo("Verificación estructural de los .m",
            OK if r.returncode == 0 else FALLA,
            r.stdout.strip().replace("\n", " | "))

    for archivo in ("microsoft/01_IIE_Estado.m", "microsoft/02_IIE_Serie_Horaria.m"):
        txt = open(archivo, encoding="utf-8").read()
        chequeo(f"Porosidad 0.53 en {os.path.basename(archivo)}",
                OK if "Porosidad = 0.53" in txt else FALLA)
        chequeo(f"Cultura en-US en {os.path.basename(archivo)}",
                OK if '"en-US"' in txt else FALLA)


def main() -> int:
    print(f"VERIFICACIÓN FINAL — {datetime.now(TZ_AR).strftime('%d/%m/%Y %H:%M')} ART")
    for fn in (v_tests, v_openmeteo, v_smn, v_matriz,
               v_salidas, v_tablero, v_workflow, v_powerquery):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            chequeo(f"{fn.__name__} lanzó excepción", FALLA, repr(exc))

    seccion("RESUMEN")
    fallas = [r for r in resultados if r[0] == FALLA]
    avisos = [r for r in resultados if r[0] == AVISO]
    print(f"  Chequeos: {len(resultados)}")
    print(f"  OK:       {len(resultados) - len(fallas) - len(avisos)}")
    print(f"  Avisos:   {len(avisos)}")
    print(f"  Fallas:   {len(fallas)}")
    for _, n, d in avisos:
        print(f"    AVISO · {n} — {d}")
    for _, n, d in fallas:
        print(f"    FALLA · {n} — {d}")
    print()
    print("  VEREDICTO:", "TODO EN ORDEN" if not fallas
          else f"HAY {len(fallas)} FALLA(S) QUE REVISAR")
    return 1 if fallas else 0


if __name__ == "__main__":
    raise SystemExit(main())
