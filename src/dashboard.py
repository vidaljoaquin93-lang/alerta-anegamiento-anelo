"""
Generador del tablero HTML estático.

Registro visual: consola de operaciones industrial, no "dashboard bonito".
Las decisiones que lo definen:

  - Densidad antes que aire. La información va en tabla, no en tarjetas
    flotantes: un despachante compara tres puntos de un vistazo, no scrollea.
  - Cifras tabulares en todo dato numérico, para que las columnas se alineen
    y las diferencias se lean sin contar dígitos.
  - Bordes de un píxel en vez de sombras. En una pantalla de guardia lo que
    importa es la separación inequívoca, no la profundidad simulada.
  - Color reservado al estado. El azul institucional es cromo (encabezado,
    títulos); verde/amarillo/rojo solo significan nivel de riesgo, nunca
    decoran. Siempre acompañados de ícono y palabra: nadie decide por matiz.
  - Metadatos visibles. Origen del dato, hora de corrida, próxima corrida y
    versión, como cualquier sistema del que dependa una decisión operativa.

LOGO INSTITUCIONAL
    Si existe `docs/logo.png` (o .svg / .jpg / .webp) se incrusta en la barra
    superior como data URI. Si no existe, se usa el distintivo con la sigla.
    El archivo lo aporta el área: debe ser el asset oficial del manual de
    marca, no una versión bajada de la web —que suele venir con el color y el
    área de resguardo equivocados.

CONSULTA PUNTUAL
    El panel de coordenadas consulta Open-Meteo desde el navegador (la API
    admite CORS) y evalúa la misma matriz con los mismos umbrales. Es la única
    parte de la página que necesita internet; el resto sigue funcionando
    abierto desde disco.
"""

from __future__ import annotations

import base64
import html
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from . import config
from .iie import saturacion_pct

log = logging.getLogger(__name__)

VERSION = "1.1"
SISTEMA_NOMBRE = "Sistema de Alerta Temprana de Anegamiento"
SISTEMA_SIGLA = "SATA"

# Ícono + palabra: el color nunca carga el significado solo.
ICONO = {"verde": "●", "amarillo": "▲", "rojo": "■"}
ETIQUETA = {"verde": "VERDE", "amarillo": "AMARILLO", "rojo": "ROJO"}

# Slots categóricos validados para daltonismo en ambos modos y en todos los
# pares. El azul institucional puro (#003da5) quedó fuera a propósito: como
# serie de datos su luminosidad (L 0.40) cae por debajo del piso de 0.43 y
# leería casi como negro sobre el gráfico. Va en el cromo, no en las líneas.
SERIE_COLORES = ["#2a78d6", "#eb6834", "#1baf7a"]
SERIE_COLORES_DARK = ["#3987e5", "#d95926", "#199e70"]

# Región donde tiene sentido evaluar avisos del SMN para una consulta puntual.
# Acota el peso de la página: sin esto habría que embeber los polígonos de todo
# el país en cada corrida.
REGION_CONSULTA = {"lat_min": -46.0, "lat_max": -30.0,
                   "lon_min": -75.0, "lon_max": -60.0}

EXTENSIONES_LOGO = (".svg", ".png", ".webp", ".jpg", ".jpeg")
MIME_LOGO = {".svg": "image/svg+xml", ".png": "image/png", ".webp": "image/webp",
             ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


# --------------------------------------------------------------------------- #
# Logo institucional
# --------------------------------------------------------------------------- #

def _logo_html() -> str:
    """
    Devuelve el <img> del logo incrustado, o el distintivo con la sigla si no
    hay archivo. Se incrusta como data URI para que la página siga siendo
    autocontenida.
    """
    for ext in EXTENSIONES_LOGO:
        ruta = os.path.join(config.DIR_DOCS, "logo" + ext)
        if not os.path.exists(ruta):
            continue
        try:
            with open(ruta, "rb") as f:
                datos = f.read()
        except OSError as exc:
            log.warning("No se pudo leer el logo %s: %s", ruta, exc)
            continue
        if len(datos) > 400_000:
            log.warning("Logo %s pesa %d KB; se omite para no inflar la página",
                        ruta, len(datos) // 1024)
            continue
        b64 = base64.b64encode(datos).decode("ascii")
        log.info("Logo institucional incrustado desde %s (%d KB)", ruta, len(datos) // 1024)
        return (f'<img class="logo" src="data:{MIME_LOGO[ext]};base64,{b64}" '
                f'alt="Logo institucional">')

    log.info("Sin docs/logo.* — se usa el distintivo con la sigla")
    return f'<div class="sigla">{SISTEMA_SIGLA}</div>'


# --------------------------------------------------------------------------- #
# Preparación de datos para los gráficos
# --------------------------------------------------------------------------- #

def _rolling_24h(valores: List[Optional[float]]) -> List[float]:
    """Acumulado móvil de 24 h sobre una serie horaria."""
    salida: List[float] = []
    ventana: List[float] = []
    for v in valores:
        ventana.append(float(v or 0.0))
        if len(ventana) > 24:
            ventana.pop(0)
        salida.append(round(sum(ventana), 2))
    return salida


def preparar_series(series: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    salida: List[Dict[str, Any]] = []
    codigos = {p.id: p.codigo for p in config.PUNTOS}
    for i, (punto_id, datos) in enumerate(series.items()):
        salida.append({
            "id": punto_id,
            "codigo": codigos.get(punto_id, ""),
            "nombre": datos["punto_nombre"],
            "color": SERIE_COLORES[i % len(SERIE_COLORES)],
            "colorDark": SERIE_COLORES_DARK[i % len(SERIE_COLORES_DARK)],
            "horas": [p["hora"] for p in datos["serie_horaria"]],
            "precip24": _rolling_24h([p["precipitacion_mm"] for p in datos["serie_horaria"]]),
            "saturacion": [saturacion_pct(p["humedad_suelo_m3m3"])
                           for p in datos["serie_horaria"]],
            "esPronostico": [p["es_pronostico"] for p in datos["serie_horaria"]],
        })
    return salida


def preparar_poligonos(avisos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Polígonos de avisos relevantes dentro de la región de consulta, para que el
    panel de coordenadas pueda evaluar el SMN sin llamar a ningún servidor.
    """
    from . import smn

    salida = []
    r = REGION_CONSULTA
    for a in avisos:
        if not smn._relevante_para_anegamiento(a):
            continue
        for pol in a.get("poligonos", []):
            lats = [v[0] for v in pol]
            lons = [v[1] for v in pol]
            if (max(lats) < r["lat_min"] or min(lats) > r["lat_max"]
                    or max(lons) < r["lon_min"] or min(lons) > r["lon_max"]):
                continue
            salida.append({
                "evento": a.get("evento"),
                "color": a.get("color_smn"),
                "expira": a.get("expira"),
                # Redondeo a 2 decimales: es la resolución de la grilla CAP,
                # así que no se pierde precisión y la página pesa la mitad.
                "pol": [[round(v[0], 2), round(v[1], 2)] for v in pol],
            })
    log.info("Polígonos SMN embebidos para consulta puntual: %d", len(salida))
    return salida


# --------------------------------------------------------------------------- #
# CSS
# --------------------------------------------------------------------------- #

CSS = """
:root{
  color-scheme: light;
  /* Azul institucional YPF y sus derivados */
  --inst:#003da5;
  --inst-vivo:#0a58d0;
  --inst-oscuro:#00205b;
  --inst-claro:#e6edf9;
  --plano:#eef1f6;
  --panel:#ffffff;
  --panel-alt:#f6f8fc;
  --linea:#d5dbe6;
  --linea-fuerte:#b6c0d2;
  --tinta:#0b1424;
  --tinta-2:#46536b;
  --tinta-3:#7b8699;
  --ok:#0ca30c;  --ok-txt:#0a7d0a;
  --warn:#fab219; --warn-txt:#8a5d00;
  --crit:#d03b3b; --crit-txt:#b02a2a;
  --zona-warn:rgba(250,178,25,.09);
  --zona-crit:rgba(208,59,59,.08);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme: dark;
    --inst:#5b8cf0; --inst-vivo:#7aa4f5; --inst-oscuro:#00132f; --inst-claro:#11244a;
    --plano:#080f1c; --panel:#101b2e; --panel-alt:#0c1627;
    --linea:#22314a; --linea-fuerte:#324563;
    --tinta:#eef2f8; --tinta-2:#a7b4c9; --tinta-3:#7d8a9e;
    --ok:#0ca30c; --ok-txt:#3fce3f;
    --warn:#fab219; --warn-txt:#f0b53a;
    --crit:#d03b3b; --crit-txt:#f07070;
    --zona-warn:rgba(250,178,25,.10);
    --zona-crit:rgba(208,59,59,.11);
  }
}

*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--plano); color:var(--tinta);
  font:13.5px/1.5 "Segoe UI",system-ui,-apple-system,sans-serif;
  -webkit-font-smoothing:antialiased;
}

/* ══════════ Barra de sistema ══════════ */
.barra{background:var(--inst-oscuro); color:#fff; border-bottom:3px solid var(--inst-vivo)}
.barra-in{
  max-width:1320px; margin:0 auto; padding:12px 22px;
  display:flex; flex-wrap:wrap; gap:14px 22px; align-items:center; justify-content:space-between;
}
.marca{display:flex; align-items:center; gap:15px; min-width:0}
.logo{height:30px; width:auto; display:block; flex-shrink:0}
.sigla{
  background:var(--inst-vivo); color:#fff; font-weight:700; font-size:14px;
  letter-spacing:.10em; padding:6px 11px; border-radius:3px; flex-shrink:0;
}
.marca-sep{width:1px; align-self:stretch; background:rgba(255,255,255,.22); flex-shrink:0}
.marca-txt{min-width:0}
.marca-t{font-size:14px; font-weight:600; line-height:1.25}
.marca-s{font-size:11.5px; color:#9fb4da; letter-spacing:.03em; margin-top:2px}
.meta{display:flex; gap:26px; font-size:11.5px; text-align:right; font-variant-numeric:tabular-nums}
.meta-k{color:#8ea6d2; text-transform:uppercase; letter-spacing:.09em; font-size:10px}
.meta-v{color:#fff; margin-top:3px; font-weight:600}
.meta-v.alarma{color:#ff9c9c}

.wrap{max-width:1320px; margin:0 auto; padding:20px 22px 56px}

.stale{
  background:var(--crit); color:#fff; padding:11px 16px; margin-bottom:18px;
  border-radius:3px; font-size:13px; line-height:1.5;
}

/* ══════════ Banda de estado ══════════ */
.estado{
  background:var(--panel); border:1px solid var(--linea);
  border-left:7px solid var(--nivel); border-radius:3px; margin-bottom:22px;
}
.estado-fila{display:flex; flex-wrap:wrap; gap:18px 30px; align-items:center; padding:17px 22px}
.estado-bloque{display:flex; align-items:center; gap:15px; flex-shrink:0}
.estado-ico{font-size:29px; line-height:1; color:var(--nivel)}
.rotulo{font-size:10px; letter-spacing:.13em; text-transform:uppercase; color:var(--tinta-3); font-weight:600}
.estado-nivel{font-size:27px; font-weight:700; line-height:1.1; color:var(--nivel); margin-top:3px}
.estado-accion{font-size:14px; color:var(--tinta); line-height:1.45; flex:1; min-width:260px}
.estado-pie{
  border-top:1px solid var(--linea); padding:11px 22px; font-size:12.5px;
  color:var(--tinta-2); display:flex; gap:10px; align-items:baseline; background:var(--panel-alt);
}
.estado-pie b{color:var(--tinta); font-weight:650}
.estado-pie .pico{color:var(--pron); font-weight:700}

/* ══════════ Secciones ══════════ */
.sec{
  display:flex; align-items:baseline; gap:12px; margin:26px 0 10px;
  border-bottom:2px solid var(--linea-fuerte); padding-bottom:7px;
}
.sec h2{font-size:12px; letter-spacing:.13em; text-transform:uppercase; color:var(--inst); font-weight:700; margin:0}
.sec span{font-size:11.5px; color:var(--tinta-3)}

/* ══════════ Tablas ══════════ */
.tabla-caja{background:var(--panel); border:1px solid var(--linea); border-radius:3px; overflow-x:auto}
table.datos{width:100%; border-collapse:collapse; font-size:13px; min-width:860px}
table.datos thead th{
  background:var(--panel-alt); color:var(--tinta-3); font-weight:600; font-size:10px;
  letter-spacing:.09em; text-transform:uppercase; padding:9px 12px; text-align:right;
  border-bottom:2px solid var(--linea-fuerte); white-space:nowrap;
}
table.datos thead th.izq{text-align:left}
table.datos tbody td{
  padding:11px 12px; text-align:right; border-bottom:1px solid var(--linea);
  font-variant-numeric:tabular-nums; white-space:nowrap;
}
table.datos tbody td.izq{text-align:left; font-variant-numeric:normal}
table.datos tbody tr:last-child td{border-bottom:none}
table.datos tbody tr:hover td{background:var(--panel-alt)}
.cod{font-family:ui-monospace,"Cascadia Mono",Consolas,monospace; font-size:12px; color:var(--tinta-2); font-weight:600}
.pnombre{font-weight:600}
.pdesc{font-size:11.5px; color:var(--tinta-3); margin-top:2px; font-weight:400}
.badge{
  display:inline-flex; align-items:center; gap:6px; padding:3px 9px; border-radius:3px;
  font-size:11px; font-weight:700; letter-spacing:.06em; border:1px solid currentColor; white-space:nowrap;
}
.b-verde{color:var(--ok-txt)}
.b-amarillo{color:var(--warn-txt)}
.b-rojo{color:var(--crit-txt)}
.iie-cel{font-size:17px; font-weight:700}
.barrita{height:4px; background:var(--linea); border-radius:2px; margin-top:5px; width:64px; margin-left:auto; overflow:hidden}
.barrita i{display:block; height:100%; background:var(--nivel)}
.motivo{font-size:11.5px; color:var(--tinta-2); text-align:left !important; white-space:normal !important; max-width:270px; line-height:1.4}
.sub{color:var(--tinta-3); font-size:11px}

/* ══════════ Paneles y gráficos ══════════ */
.panel{background:var(--panel); border:1px solid var(--linea); border-radius:3px; padding:16px 18px 10px; margin-bottom:14px}
.panel-t{font-size:13.5px; font-weight:650; margin-bottom:3px}
.panel-s{font-size:11.5px; color:var(--tinta-2); margin-bottom:13px; line-height:1.45}
.leyenda{display:flex; flex-wrap:wrap; gap:16px; margin-bottom:11px; font-size:11.5px; color:var(--tinta-2)}
.leyenda span{display:inline-flex; align-items:center; gap:7px}
.sw{width:15px; height:3px; border-radius:2px; display:inline-block}
svg{display:block; width:100%; height:auto}
.scroll-x{overflow-x:auto}
.tip{
  position:fixed; pointer-events:none; z-index:30; opacity:0; transition:opacity .1s;
  background:var(--panel); border:1px solid var(--linea-fuerte); border-radius:3px;
  padding:9px 11px; font-size:12px; box-shadow:0 6px 22px rgba(0,32,91,.20); min-width:190px;
}
.tip b{display:block; font-size:10.5px; color:var(--tinta-3); font-weight:700; margin-bottom:7px; text-transform:uppercase; letter-spacing:.07em}
.tip .r{display:flex; align-items:center; gap:12px; justify-content:space-between; margin-top:4px}
.tip .r em{font-style:normal; color:var(--tinta-2); display:flex; align-items:center; gap:7px}
.tip .r strong{font-variant-numeric:tabular-nums; font-weight:700}

/* ══════════ Consulta puntual ══════════ */
.consulta{background:var(--panel); border:1px solid var(--linea); border-radius:3px; padding:16px 18px}
.form{display:flex; flex-wrap:wrap; gap:12px 16px; align-items:flex-end; margin-bottom:4px}
.campo{display:flex; flex-direction:column; gap:5px}
.campo label{font-size:10px; letter-spacing:.1em; text-transform:uppercase; color:var(--tinta-3); font-weight:700}
.campo input, .campo select{
  font:13px/1.4 "Segoe UI",system-ui,sans-serif; font-variant-numeric:tabular-nums;
  padding:8px 10px; border:1px solid var(--linea-fuerte); border-radius:3px;
  background:var(--panel); color:var(--tinta); min-width:150px;
}
.campo input:focus, .campo select:focus{outline:2px solid var(--inst-vivo); outline-offset:-1px; border-color:var(--inst-vivo)}
.btn{
  font:600 13px/1 "Segoe UI",system-ui,sans-serif; padding:10px 20px; border:none; border-radius:3px;
  background:var(--inst); color:#fff; cursor:pointer; letter-spacing:.02em;
}
.btn:hover{background:var(--inst-vivo)}
.btn:disabled{opacity:.55; cursor:default}
.btn-sec{background:transparent; color:var(--inst); border:1px solid var(--linea-fuerte)}
.btn-sec:hover{background:var(--inst-claro)}
.ayuda{font-size:11.5px; color:var(--tinta-3); margin-top:10px; line-height:1.5}
.res{margin-top:18px; padding-top:16px; border-top:2px solid var(--linea-fuerte)}
.res[hidden]{display:none}
.res-cab{display:flex; flex-wrap:wrap; gap:14px 26px; align-items:center; margin-bottom:14px}
.res-nivel{display:flex; align-items:center; gap:12px}
.res-ico{font-size:24px; color:var(--nivel)}
.res-txt{font-size:21px; font-weight:700; color:var(--nivel); line-height:1.1}
.res-coord{font-family:ui-monospace,Consolas,monospace; font-size:12px; color:var(--tinta-2)}
.res-grid{display:grid; grid-template-columns:repeat(auto-fit,minmax(132px,1fr)); gap:1px; background:var(--linea); border:1px solid var(--linea); margin-bottom:14px}
.res-celda{background:var(--panel); padding:10px 12px}
.res-k{font-size:9.5px; letter-spacing:.1em; text-transform:uppercase; color:var(--tinta-3); font-weight:700}
.res-v{font-size:17px; font-weight:700; font-variant-numeric:tabular-nums; margin-top:4px}
.res-u{font-size:11px; color:var(--tinta-3); font-weight:400}
.res-nota{font-size:12px; color:var(--tinta-2); line-height:1.5; margin-top:10px}
.err{background:var(--zona-crit); border:1px solid var(--crit); color:var(--crit-txt); padding:10px 13px; border-radius:3px; font-size:12.5px; margin-top:14px}
.cargando{font-size:12.5px; color:var(--tinta-2); margin-top:14px}

/* ══════════ Avisos SMN ══════════ */
.aviso{background:var(--panel); border:1px solid var(--linea); border-left:4px solid var(--warn); border-radius:3px; padding:12px 16px; margin-bottom:9px}
.aviso.naranja{border-left-color:#ec835a}
.aviso.rojo{border-left-color:var(--crit)}
.aviso.ninguno{border-left-color:var(--ok)}
.aviso-t{font-size:12.5px; font-weight:700; margin-bottom:5px; display:flex; flex-wrap:wrap; gap:10px; align-items:baseline}
.aviso-t .org{font-family:ui-monospace,Consolas,monospace; font-size:10.5px; color:var(--tinta-3); font-weight:600; letter-spacing:.05em}
.aviso p{margin:0; font-size:12.5px; color:var(--tinta-2); line-height:1.5}
.aviso-meta{font-size:11px; color:var(--tinta-3); margin-top:7px; font-variant-numeric:tabular-nums; display:flex; flex-wrap:wrap; gap:16px}

/* ══════════ Matriz ══════════ */
.matriz{width:100%; border-collapse:collapse; font-size:12px}
.matriz th{background:var(--panel-alt); font-size:10px; letter-spacing:.09em; text-transform:uppercase; color:var(--tinta-3); font-weight:600; padding:8px 12px; text-align:left; border-bottom:2px solid var(--linea-fuerte)}
.matriz td{padding:9px 12px; border-bottom:1px solid var(--linea); vertical-align:top}
.matriz tr:last-child td{border-bottom:none}
.matriz td:first-child{white-space:nowrap; font-weight:700}

/* ══════════ Pie ══════════ */
.pie{
  margin-top:30px; border-top:2px solid var(--linea-fuerte); padding-top:16px;
  display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:20px 34px;
  font-size:11.5px; color:var(--tinta-2); line-height:1.65;
}
.pie h3{font-size:10px; letter-spacing:.12em; text-transform:uppercase; color:var(--tinta-3); font-weight:700; margin:0 0 7px}
.pie code{font-family:ui-monospace,Consolas,monospace; font-size:11px; background:var(--inst-claro); color:var(--inst); padding:1px 5px; border-radius:2px}
.pie dl{display:grid; grid-template-columns:auto 1fr; gap:3px 12px; margin:0}
.pie dt{color:var(--tinta-3)}
.pie dd{margin:0; font-variant-numeric:tabular-nums}

@media(max-width:720px){
  .wrap{padding:14px 13px 40px}
  .barra-in{padding:10px 13px}
  .meta{gap:18px}
  .estado-nivel{font-size:23px}
  .estado-fila{padding:14px 16px}
  .campo input, .campo select{min-width:120px}
}
"""


# --------------------------------------------------------------------------- #
# JS
# --------------------------------------------------------------------------- #

JS = r"""
(function(){
  const D = window.__DATOS__;
  const dark = () => matchMedia('(prefers-color-scheme: dark)').matches
                     && document.documentElement.dataset.theme !== 'light';
  const col = s => dark() ? s.colorDark : s.color;
  const css = v => getComputedStyle(document.body).getPropertyValue(v).trim();
  const NS='http://www.w3.org/2000/svg';
  const el=(n,a={})=>{const e=document.createElementNS(NS,n);
    for(const k in a) e.setAttribute(k,a[k]); return e;};
  const tip = document.getElementById('tip');
  const DIAS=['dom','lun','mar','mié','jue','vie','sáb'];

  function fmtHora(iso){
    const d=new Date(iso);
    return DIAS[d.getDay()]+' '+String(d.getDate()).padStart(2,'0')+'/'
      +String(d.getMonth()+1).padStart(2,'0')+' '+String(d.getHours()).padStart(2,'0')+':00';
  }

  // ── Gráfico de series ──────────────────────────────────────────────────
  function dibujar(cfg){
    const host=document.getElementById(cfg.id);
    if(!host) return;
    host.innerHTML='';

    const W=1000, H=cfg.alto||236, m={t:16,r:114,b:30,l:46};
    const iw=W-m.l-m.r, ih=H-m.t-m.b;
    const series=cfg.series||D.series;
    const n=series[0][cfg.campo].length;
    const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,role:'img','aria-label':cfg.aria,
      preserveAspectRatio:'xMidYMid meet'});

    let max=0;
    series.forEach(s=>s[cfg.campo].forEach(v=>{if(v!=null&&v>max)max=v;}));
    cfg.umbrales.forEach(u=>{if(u.v>max)max=u.v;});
    max = cfg.max != null ? cfg.max : (max*1.2||1);

    const x=i=>m.l+(i/(n-1))*iw;
    const y=v=>m.t+ih-(Math.min(v,max)/max)*ih;

    // Zonas de riesgo: bandas tenues de fondo. Comunican el umbral sin
    // competir con las líneas, y sobreviven a una impresión en blanco y negro
    // porque además están las líneas de corte rotuladas.
    const zonas=[
      {desde:cfg.umbrales[0].v, hasta:cfg.umbrales[1].v, fill:css('--zona-warn')},
      {desde:cfg.umbrales[1].v, hasta:max,               fill:css('--zona-crit')}
    ];
    zonas.forEach(z=>{
      if(z.hasta<=z.desde) return;
      svg.appendChild(el('rect',{x:m.l,y:y(z.hasta),width:iw,
        height:Math.max(0,y(z.desde)-y(z.hasta)),fill:z.fill}));
    });

    // Grilla horizontal
    for(let k=0;k<=4;k++){
      const v=max*k/4, yy=y(v);
      svg.appendChild(el('line',{x1:m.l,x2:m.l+iw,y1:yy,y2:yy,
        stroke:css('--linea'),'stroke-width':1,'stroke-dasharray':k?'1 4':'0'}));
      const t=el('text',{x:m.l-9,y:yy+4,'text-anchor':'end',fill:css('--tinta-3'),
        'font-size':10.5,'font-family':'Segoe UI,system-ui,sans-serif'});
      t.textContent=(max>=20?Math.round(v):v.toFixed(1));
      svg.appendChild(t);
    }

    // Líneas de umbral
    cfg.umbrales.forEach(u=>{
      svg.appendChild(el('line',{x1:m.l,x2:m.l+iw,y1:y(u.v),y2:y(u.v),
        stroke:u.color,'stroke-width':1.5,'stroke-dasharray':'6 4',opacity:.85}));
      const t=el('text',{x:m.l+iw+7,y:y(u.v)+3.5,fill:u.color,'font-size':10,
        'font-weight':700,'font-family':'Segoe UI,system-ui,sans-serif'});
      t.textContent=u.etiqueta;
      svg.appendChild(t);
    });

    // Separador observado / pronóstico
    const iAhora=series[0].esPronostico.findIndex(p=>p);
    if(iAhora>0){
      const xa=x(iAhora);
      svg.appendChild(el('rect',{x:xa,y:m.t,width:m.l+iw-xa,height:ih,
        fill:css('--tinta-3'),opacity:.035}));
      svg.appendChild(el('line',{x1:xa,x2:xa,y1:m.t,y2:m.t+ih,
        stroke:css('--linea-fuerte'),'stroke-width':1.25,'stroke-dasharray':'3 3'}));
      const t=el('text',{x:xa+6,y:m.t+10,fill:css('--tinta-3'),'font-size':9.5,
        'font-weight':700,'letter-spacing':'.08em','font-family':'Segoe UI,system-ui,sans-serif'});
      t.textContent='PRONÓSTICO →';
      svg.appendChild(t);
    }

    // Eje X
    for(let i=0;i<n;i+=24){
      const t=el('text',{x:x(i),y:H-9,'text-anchor':'middle',fill:css('--tinta-3'),
        'font-size':10.5,'font-family':'Segoe UI,system-ui,sans-serif'});
      const d=new Date(series[0].horas[i]);
      t.textContent=String(d.getDate()).padStart(2,'0')+'/'+String(d.getMonth()+1).padStart(2,'0');
      svg.appendChild(t);
    }
    svg.appendChild(el('line',{x1:m.l,x2:m.l+iw,y1:m.t+ih,y2:m.t+ih,
      stroke:css('--linea-fuerte'),'stroke-width':1}));

    // Series
    const etiquetas=[];
    series.forEach((s,si)=>{
      const v=s[cfg.campo];
      const corte=iAhora>0?iAhora:n-1;

      // Relleno bajo la curva: solo con una serie. Con tres se ensucia y deja
      // de leerse cuál está arriba.
      if(series.length===1){
        const gid='grad'+cfg.id+si;
        const defs=el('defs');
        const g=el('linearGradient',{id:gid,x1:0,y1:0,x2:0,y2:1});
        g.appendChild(el('stop',{offset:'0%','stop-color':col(s),'stop-opacity':.28}));
        g.appendChild(el('stop',{offset:'100%','stop-color':col(s),'stop-opacity':0}));
        defs.appendChild(g); svg.appendChild(defs);
        let d='';
        for(let i=0;i<n;i++){ if(v[i]==null) continue;
          d+=(d?'L':'M')+x(i).toFixed(1)+' '+y(v[i]).toFixed(1); }
        if(d){
          d+=`L${x(n-1).toFixed(1)} ${(m.t+ih).toFixed(1)}L${x(0).toFixed(1)} ${(m.t+ih).toFixed(1)}Z`;
          svg.appendChild(el('path',{d,fill:`url(#${gid})`,stroke:'none'}));
        }
      }

      const seg=(desde,hasta,dash)=>{
        let d='';
        for(let i=desde;i<=hasta;i++){ if(v[i]==null) continue;
          d+=(d?'L':'M')+x(i).toFixed(1)+' '+y(v[i]).toFixed(1); }
        if(!d) return;
        const p=el('path',{d,fill:'none',stroke:col(s),'stroke-width':2.25,
          'stroke-linecap':'round','stroke-linejoin':'round'});
        if(dash) p.setAttribute('stroke-dasharray','5 4');
        svg.appendChild(p);
      };
      seg(0,corte,false); seg(corte,n-1,true);

      let ult=n-1; while(ult>0&&v[ult]==null) ult--;
      if(v[ult]!=null) etiquetas.push({y:y(v[ult]),color:col(s),texto:s.codigo});
    });

    // Etiquetas directas con anti-colisión
    etiquetas.sort((a,b)=>a.y-b.y);
    for(let i=1;i<etiquetas.length;i++)
      if(etiquetas[i].y-etiquetas[i-1].y<13) etiquetas[i].y=etiquetas[i-1].y+13;
    const exceso=etiquetas.length?Math.max(0,etiquetas[etiquetas.length-1].y-(m.t+ih)):0;
    etiquetas.forEach(e=>{
      const t=el('text',{x:m.l+iw+7,y:e.y-exceso+4,fill:e.color,'font-size':10.5,
        'font-weight':700,'font-family':'ui-monospace,Consolas,monospace'});
      t.textContent=e.texto; svg.appendChild(t);
    });

    // Hover
    const banda=el('rect',{y:m.t,height:ih,width:Math.max(3,iw/n),
      fill:css('--inst'),opacity:0});
    svg.appendChild(banda);
    const pts=series.map(s=>{
      const c=el('circle',{r:4.5,fill:col(s),stroke:css('--panel'),'stroke-width':2.5,opacity:0});
      svg.appendChild(c); return c;
    });
    const hit=el('rect',{x:m.l,y:m.t,width:iw,height:ih,fill:'transparent'});
    svg.appendChild(hit);

    function mover(ev){
      const r=svg.getBoundingClientRect();
      const px=(ev.touches?ev.touches[0].clientX:ev.clientX)-r.left;
      const i=Math.max(0,Math.min(n-1,Math.round(((px/r.width*W)-m.l)/iw*(n-1))));
      banda.setAttribute('x',x(i)-iw/n/2); banda.setAttribute('opacity',.07);
      let filas='';
      series.forEach((s,k)=>{
        const v=s[cfg.campo][i];
        if(v==null){pts[k].setAttribute('opacity',0); return;}
        pts[k].setAttribute('cx',x(i)); pts[k].setAttribute('cy',y(v));
        pts[k].setAttribute('opacity',1);
        filas+=`<div class="r"><em><span class="sw" style="background:${col(s)}"></span>${s.codigo?s.codigo+' ':''}${s.nombre}</em><strong>${v.toFixed(1)}${cfg.unidad}</strong></div>`;
      });
      tip.innerHTML=`<b>${fmtHora(series[0].horas[i])} · ${series[0].esPronostico[i]?'pronóstico':'observado'}</b>${filas}`;
      tip.style.opacity=1;
      const cx=(ev.touches?ev.touches[0].clientX:ev.clientX);
      const cy=(ev.touches?ev.touches[0].clientY:ev.clientY);
      tip.style.left=Math.min(innerWidth-tip.offsetWidth-10,Math.max(8,cx+16))+'px';
      tip.style.top=Math.max(8,cy-tip.offsetHeight-14)+'px';
    }
    function salir(){
      tip.style.opacity=0; banda.setAttribute('opacity',0);
      pts.forEach(p=>p.setAttribute('opacity',0));
    }
    hit.addEventListener('mousemove',mover);
    hit.addEventListener('mouseleave',salir);
    hit.addEventListener('touchmove',e=>{mover(e);e.preventDefault();},{passive:false});
    hit.addEventListener('touchend',salir);

    host.appendChild(svg);
  }

  function todo(){
    dibujar({id:'g-precip', campo:'precip24', unidad:' mm', alto:236,
      aria:'Precipitación acumulada móvil de 24 horas por punto de control',
      umbrales:[{v:D.umbrales.precipAmarillo,etiqueta:'3 mm',color:css('--warn')},
                {v:D.umbrales.precipRojo,etiqueta:'7 mm',color:css('--crit')}]});
    dibujar({id:'g-suelo', campo:'saturacion', unidad:' %', alto:236, max:100,
      aria:'Saturación de humedad del suelo por punto de control',
      umbrales:[{v:D.umbrales.satAmarillo,etiqueta:'60 %',color:css('--warn')},
                {v:D.umbrales.satRojo,etiqueta:'75 %',color:css('--crit')}]});
    if(window.__ULTIMA_CONSULTA__) dibujarConsulta(window.__ULTIMA_CONSULTA__);
  }
  todo();
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change',todo);
  let t; addEventListener('resize',()=>{clearTimeout(t);t=setTimeout(todo,180);});

  // ── Frescura del dato ──────────────────────────────────────────────────
  function frescura(){
    const e=document.getElementById('frescura');
    if(!e) return;
    const ts=new Date(e.dataset.ts+'-03:00');
    if(isNaN(ts)) return;
    const min=Math.floor((Date.now()-ts.getTime())/60000);
    let txt, alarma=false;
    if(min<0) txt='—';
    else if(min<90) txt='hace '+min+' min';
    else if(min<180) txt='hace '+Math.floor(min/60)+' h '+(min%60)+' min';
    else { txt='DESACTUALIZADO · '+Math.floor(min/60)+' h'; alarma=true; }
    e.textContent=txt; e.classList.toggle('alarma',alarma);
    const b=document.getElementById('banner-stale');
    if(b) b.hidden=!alarma;
  }
  frescura(); setInterval(frescura,60000);

  // ══════════════════════════════════════════════════════════════════════
  //  CONSULTA PUNTUAL POR COORDENADAS
  // ══════════════════════════════════════════════════════════════════════
  const U=D.umbrales, POROS=D.porosidad;

  function puntoEnPoligono(lat,lon,pol){
    let dentro=false;
    for(let i=0,j=pol.length-1;i<pol.length;j=i++){
      const yi=pol[i][0], xi=pol[i][1], yj=pol[j][0], xj=pol[j][1];
      if((yi>lat)!==(yj>lat)){
        const xc=(xj-xi)*(lat-yi)/(yj-yi)+xi;
        if(lon<xc) dentro=!dentro;
      }
    }
    return dentro;
  }
  function avisoSobre(lat,lon){
    const B=D.bufferGrados, g=B*0.7071;
    const desp=[[0,0],[B,0],[-B,0],[0,B],[0,-B],[g,g],[g,-g],[-g,g],[-g,-g]];
    const orden={amarillo:1,naranja:2,rojo:3};
    let peor=null;
    for(const a of (D.poligonosSmn||[])){
      if(desp.some(d=>puntoEnPoligono(lat+d[0],lon+d[1],a.pol))){
        if(!peor || orden[a.color]>orden[peor.color]) peor=a;
      }
    }
    return peor;
  }
  function nivelDe(precipRef,sat,colorSmn){
    let n = precipRef>U.precipRojo ? 2 : (precipRef>=U.precipAmarillo ? 1 : 0);
    if(sat!=null) n = Math.max(n, sat>U.satRojo ? 2 : (sat>=U.satAmarillo ? 1 : 0));
    if(colorSmn==='naranja'||colorSmn==='rojo') n=2;
    else if(colorSmn==='amarillo') n=Math.max(n,1);
    return ['verde','amarillo','rojo'][n];
  }
  function iieDe(precipRef,sat,colorSmn){
    const sp=Math.min(100,precipRef/12*100);
    const ss=sat==null?0:Math.max(0,Math.min(100,(sat-40)/45*100));
    let v = sat==null ? sp : 0.55*sp+0.45*ss;
    const piso={amarillo:50,naranja:75,rojo:90}[colorSmn];
    if(piso) v=Math.max(v,piso);
    return Math.round(Math.min(100,v)*10)/10;
  }

  const $=id=>document.getElementById(id);
  const ICO={verde:'●',amarillo:'▲',rojo:'■'};
  const ETI={verde:'VERDE',amarillo:'AMARILLO',rojo:'ROJO'};
  const VARCOL={verde:'var(--ok)',amarillo:'var(--warn)',rojo:'var(--crit)'};
  const ACC={
    verde:'Transitabilidad normal. Sin restricciones.',
    amarillo:'Barro en greda. Circular solo con 4x4. Evitar equipos pesados sin escolta.',
    rojo:'Anegamiento inminente / cortes de picadas. Suspender movimientos no críticos.'};

  function dibujarConsulta(datos){
    dibujar({id:'g-consulta', campo:'precip24', unidad:' mm', alto:200,
      series:[datos.serie], aria:'Precipitación acumulada en el punto consultado',
      umbrales:[{v:U.precipAmarillo,etiqueta:'3 mm',color:css('--warn')},
                {v:U.precipRojo,etiqueta:'7 mm',color:css('--crit')}]});
  }

  async function consultar(){
    const lat=parseFloat($('c-lat').value), lon=parseFloat($('c-lon').value);
    const err=$('c-error'), res=$('c-res'), cargando=$('c-cargando');
    err.hidden=true; res.hidden=true;

    if(isNaN(lat)||isNaN(lon)||lat<-90||lat>90||lon<-180||lon>180){
      err.textContent='Coordenadas inválidas. La latitud va de -90 a 90 y la longitud de -180 a 180. En Argentina ambas son negativas (por ejemplo -38.353 y -68.783).';
      err.hidden=false; return;
    }

    cargando.hidden=false; $('c-btn').disabled=true;
    try{
      const u=new URL('https://api.open-meteo.com/v1/forecast');
      u.search=new URLSearchParams({latitude:lat,longitude:lon,
        hourly:'precipitation,soil_moisture_0_to_7cm,temperature_2m,wind_speed_10m',
        past_days:3, forecast_days:3, timezone:'America/Argentina/Buenos_Aires'});
      // Sin timeout explícito, un fetch que no resuelve deja el panel en
      // "Consultando…" para siempre y el operador no sabe si esperar.
      const ctrl=new AbortController();
      const to=setTimeout(()=>ctrl.abort(),15000);
      let r;
      try{ r=await fetch(u,{signal:ctrl.signal}); }
      finally{ clearTimeout(to); }
      if(!r.ok) throw new Error('la API respondió '+r.status);
      const j=await r.json();
      const h=j.hourly;
      const horas=h.time, precip=h.precipitation.map(v=>v==null?0:v);
      const suelo=h.soil_moisture_0_to_7cm;

      const ahora=new Date(Date.now()-3*3600*1000);
      const idx=72+ahora.getUTCHours();
      const suma=(a,d,c)=>{const n=Math.max(0,Math.min(c,a.length-d));
        return n<=0?0:a.slice(d,d+n).reduce((x,y)=>x+y,0);};
      const acum=suma(precip,Math.max(0,idx-23),24);
      const p24=suma(precip,idx+1,24), p72=suma(precip,idx+1,72);
      const ref=Math.max(acum,p24);
      const sm=suelo[idx];
      const sat=sm==null?null:Math.min(100,sm/POROS*100);

      const av=avisoSobre(lat,lon);
      const color=av?av.color:null;
      const nivel=nivelDe(ref,sat,color), iie=iieDe(ref,sat,color);

      // acumulado móvil para el mini gráfico
      const roll=[]; let vent=[];
      for(const v of precip){ vent.push(v); if(vent.length>24) vent.shift();
        roll.push(Math.round(vent.reduce((a,b)=>a+b,0)*100)/100); }

      window.__ULTIMA_CONSULTA__={serie:{codigo:'',nombre:'Punto consultado',
        color:'#2a78d6',colorDark:'#3987e5',horas,precip24:roll,
        esPronostico:horas.map((_,i)=>i>idx)}};

      $('c-ico').textContent=ICO[nivel];
      $('c-nivel').textContent=ETI[nivel];
      res.style.setProperty('--nivel',VARCOL[nivel]);
      $('c-coord').textContent=lat.toFixed(4)+', '+lon.toFixed(4)
        +'  ·  '+Math.round(j.elevation)+' m s.n.m.';
      $('c-ref').textContent=ref.toFixed(1);
      $('c-acum').textContent=acum.toFixed(1);
      $('c-p24').textContent=p24.toFixed(1);
      $('c-p72').textContent=p72.toFixed(1);
      $('c-sat').textContent=sat==null?'s/d':Math.round(sat);
      $('c-sm').textContent=sm==null?'':sm.toFixed(3)+' m³/m³';
      $('c-iie').textContent=iie.toFixed(0);
      $('c-smn').textContent=av?ETI[av.color]:'—';
      $('c-smn').className='res-v '+(av?'b-'+av.color:'');
      $('c-accion').textContent=ACC[nivel];
      $('c-detalle').textContent = av
        ? 'Aviso SMN de '+av.evento+' vigente sobre este punto, con vencimiento '+av.expira.slice(0,16).replace('T',' ')+'.'
        : 'Sin avisos del SMN vigentes sobre este punto entre los relevantes para anegamiento.';

      res.hidden=false;
      dibujarConsulta(window.__ULTIMA_CONSULTA__);
    }catch(e){
      err.textContent = (e.name==='AbortError')
        ? 'La consulta a Open-Meteo tardó más de 15 segundos y se canceló. Reintentá; si persiste, puede ser la red de la empresa bloqueando el dominio.'
        : 'No se pudo consultar Open-Meteo: '+e.message+'. Esta función necesita conexión a internet; el resto del tablero funciona sin ella.';
      err.hidden=false;
    }finally{
      cargando.hidden=true; $('c-btn').disabled=false;
    }
  }

  if($('c-btn')){
    $('c-btn').addEventListener('click',consultar);
    $('c-preset').addEventListener('change',function(){
      if(!this.value) return;
      const [la,lo]=this.value.split(',');
      $('c-lat').value=la; $('c-lon').value=lo;
    });
    ['c-lat','c-lon'].forEach(id=>$(id).addEventListener('keydown',e=>{
      if(e.key==='Enter') consultar();
    }));
  }
})();
"""


# --------------------------------------------------------------------------- #
# Utilidades de render
# --------------------------------------------------------------------------- #

def _e(x: Any) -> str:
    return html.escape("" if x is None else str(x))


def _n(v: Any, dec: int = 1, suf: str = "") -> str:
    if v is None or v == "":
        return '<span class="sub">s/d</span>'
    try:
        return f"{float(v):.{dec}f}{suf}"
    except (TypeError, ValueError):
        return _e(v)


COLOR_NIVEL = {"verde": "var(--ok)", "amarillo": "var(--warn)", "rojo": "var(--crit)"}


def _fmt_hora(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    try:
        d = datetime.fromisoformat(iso)
        return f"{d.day:02d}/{d.month:02d} {d.hour:02d}:00"
    except ValueError:
        return _e(iso)


def _fila_punto(p: Dict[str, Any]) -> str:
    nivel = p["nivel"]
    motivo = " · ".join(p.get("disparadores", []))
    pron = p.get("nivel_pronosticado", "verde")

    if config.ORDEN_NIVELES.get(pron, 0) > config.ORDEN_NIVELES.get(nivel, 0):
        horas = p.get("horas_hasta_pico")
        proy = (f'<span style="color:{COLOR_NIVEL[pron]};font-weight:700">'
                f'{ICONO[pron]} {ETIQUETA[pron]}</span><div class="sub">'
                f'{_fmt_hora(p.get("hora_pico"))} h'
                f'{f" · en ~{horas} h" if horas else ""}</div>')
    else:
        proy = '<span class="sub">sin cambio</span>'

    smn_cel = ('<span class="badge b-' + p['alerta_smn_color'] + '">'
               + ETIQUETA.get(p['alerta_smn_color'], p['alerta_smn_color'].upper())
               + '</span>') if p.get('alerta_smn_color') else '<span class="sub">—</span>'

    return f"""<tr>
  <td class="izq"><span class="cod">{_e(p.get('punto_codigo', '—'))}</span></td>
  <td class="izq">
    <div class="pnombre">{_e(p['punto_nombre'])}</div>
    <div class="pdesc">{_e(p.get('punto_descripcion', ''))}</div>
  </td>
  <td><span class="badge b-{nivel}">{ICONO[nivel]} {ETIQUETA[nivel]}</span></td>
  <td style="--nivel:{COLOR_NIVEL[nivel]}">
    <div class="iie-cel">{_n(p['iie'], 0)}</div>
    <div class="barrita"><i style="width:{max(2, min(100, float(p['iie'] or 0)))}%"></i></div>
  </td>
  <td>{_n(p['precip_acum_24h_mm'], 1)}</td>
  <td>{_n(p['precip_pron_24h_mm'], 1)}</td>
  <td>{_n(p['precip_pron_72h_mm'], 1)}</td>
  <td>{_n(p['saturacion_suelo_pct'], 0)}<div class="sub">{_n(p['humedad_suelo_m3m3'], 3)} m³/m³</div></td>
  <td>{smn_cel}</td>
  <td>{proy}</td>
  <td class="motivo">{_e(motivo)}</td>
</tr>"""


def _aviso(a: Dict[str, Any]) -> str:
    color = a.get("color_smn", "amarillo")
    return f"""
<div class="aviso {color}">
  <div class="aviso-t">
    <span>{_e(a.get('evento'))}</span>
    <span class="org">SMN · NIVEL {color.upper()} · CAP {_e(a.get('severidad_cap'))}</span>
  </div>
  <p>{_e(a.get('descripcion'))}</p>
  <div class="aviso-meta">
    <span>Vigencia {_fmt_hora(a.get('inicio'))} → {_fmt_hora(a.get('expira'))}</span>
    <span>Certeza {_e(a.get('certeza'))}</span>
    <span>Urgencia {_e(a.get('urgencia'))}</span>
  </div>
</div>"""


def _banda_perspectiva(estado: Dict[str, Any]) -> str:
    actual = estado["nivel_consolidado"]
    peor = max((p.get("nivel_pronosticado", "verde") for p in estado["puntos"]),
               key=lambda n: config.ORDEN_NIVELES.get(n, 0), default="verde")
    if config.ORDEN_NIVELES.get(peor, 0) <= config.ORDEN_NIVELES.get(actual, 0):
        return ('<div class="estado-pie" style="--pron:var(--ok)">'
                '<span class="rotulo">Perspectiva 72 h</span>'
                '<span><b>Sin deterioro previsto.</b> Ningún punto supera los '
                'umbrales con el pronóstico vigente.</span></div>')

    criticos = [p for p in estado["puntos"] if p.get("nivel_pronosticado") == peor]
    primero = min(criticos, key=lambda p: p.get("horas_hasta_pico") or 999)
    codigos = ", ".join(p.get("punto_codigo", "") for p in criticos)
    return ('<div class="estado-pie" style="--pron:{c}">'
            '<span class="rotulo">Perspectiva 72 h</span>'
            '<span>Escalada prevista a <span class="pico">{i} {n}</span> en {cods} — '
            'pico el <b>{h} h</b> ({mm} en 24 h). Ventana de anticipación ~{hs} h.'
            '</span></div>').format(
        c=COLOR_NIVEL[peor], i=ICONO[peor], n=ETIQUETA[peor], cods=_e(codigos),
        h=_fmt_hora(primero.get("hora_pico")),
        mm=_n(primero.get("pico_precip_24h_mm"), 1, " mm"),
        hs=primero.get("horas_hasta_pico") or "—")


def _panel_consulta() -> str:
    opciones = "".join(
        f'<option value="{p.lat},{p.lon}">{_e(p.codigo)} — {_e(p.nombre)}</option>'
        for p in config.PUNTOS)
    return f"""
<div class="consulta">
  <div class="form">
    <div class="campo">
      <label for="c-preset">Punto de referencia</label>
      <select id="c-preset">
        <option value="">— coordenadas manuales —</option>
        {opciones}
      </select>
    </div>
    <div class="campo">
      <label for="c-lat">Latitud</label>
      <input id="c-lat" type="number" step="0.0001" value="-38.7619" inputmode="decimal">
    </div>
    <div class="campo">
      <label for="c-lon">Longitud</label>
      <input id="c-lon" type="number" step="0.0001" value="-68.6312" inputmode="decimal">
    </div>
    <button class="btn" id="c-btn" type="button">Consultar</button>
  </div>
  <div class="ayuda">
    Grados decimales, negativos para Argentina. Se evalúa la misma matriz y los
    mismos umbrales que los puntos fijos, contra los avisos del SMN vigentes en
    la región. Ejemplo cargado: Sierra Barrosa.
  </div>

  <div class="cargando" id="c-cargando" hidden>Consultando Open-Meteo…</div>
  <div class="err" id="c-error" hidden></div>

  <div class="res" id="c-res" hidden>
    <div class="res-cab">
      <div class="res-nivel">
        <span class="res-ico" id="c-ico"></span>
        <div>
          <div class="rotulo">Nivel en el punto</div>
          <div class="res-txt" id="c-nivel"></div>
        </div>
      </div>
      <div class="res-coord" id="c-coord"></div>
    </div>

    <div class="res-grid">
      <div class="res-celda"><div class="res-k">IIE</div><div class="res-v" id="c-iie"></div></div>
      <div class="res-celda"><div class="res-k">Lluvia ref.</div><div class="res-v"><span id="c-ref"></span> <span class="res-u">mm</span></div></div>
      <div class="res-celda"><div class="res-k">Acum. 24 h</div><div class="res-v"><span id="c-acum"></span> <span class="res-u">mm</span></div></div>
      <div class="res-celda"><div class="res-k">Pron. 24 h</div><div class="res-v"><span id="c-p24"></span> <span class="res-u">mm</span></div></div>
      <div class="res-celda"><div class="res-k">Pron. 72 h</div><div class="res-v"><span id="c-p72"></span> <span class="res-u">mm</span></div></div>
      <div class="res-celda"><div class="res-k">Saturación</div><div class="res-v"><span id="c-sat"></span> <span class="res-u">%</span><div class="sub" id="c-sm"></div></div></div>
      <div class="res-celda"><div class="res-k">Aviso SMN</div><div class="res-v" id="c-smn"></div></div>
    </div>

    <div class="res-nota"><b id="c-accion"></b></div>
    <div class="res-nota" id="c-detalle"></div>
    <div class="scroll-x" style="margin-top:14px"><div id="g-consulta"></div></div>
  </div>
</div>"""


# --------------------------------------------------------------------------- #
# Render principal
# --------------------------------------------------------------------------- #

def construir_cuerpo(estado: Dict[str, Any],
                     series: Dict[str, Dict[str, Any]],
                     avisos: Optional[List[Dict[str, Any]]] = None) -> str:
    nivel = estado["nivel_consolidado"]
    datos_js = {
        "series": preparar_series(series),
        "umbrales": {
            "precipAmarillo": config.PRECIP_AMARILLO_MM,
            "precipRojo": config.PRECIP_ROJO_MM,
            "satAmarillo": config.SATURACION_AMARILLO_PCT,
            "satRojo": config.SATURACION_ROJO_PCT,
        },
        "porosidad": config.POROSIDAD_TOTAL,
        "bufferGrados": config.BUFFER_ALERTA_GRADOS,
        "poligonosSmn": preparar_poligonos(avisos or []),
    }

    alertas = estado.get("alertas_smn_vigentes_zona", [])
    bloque_avisos = "".join(_aviso(a) for a in alertas) if alertas else (
        '<div class="aviso ninguno"><div class="aviso-t"><span>Sin avisos vigentes</span>'
        '<span class="org">SMN · FEED CAP</span></div>'
        '<p>Ningún aviso del Servicio Meteorológico Nacional tiene un polígono que '
        'contenga los puntos de control monitoreados.</p></div>')

    leyenda = "".join(
        f'<span><i class="sw" style="background:{s["color"]}"></i>'
        f'<b class="cod">{_e(s["codigo"])}</b> {_e(s["nombre"])}</span>'
        for s in datos_js["series"])

    return f"""<style>{CSS}</style>

<header class="barra">
  <div class="barra-in">
    <div class="marca">
      {_logo_html()}
      <div class="marca-sep"></div>
      <div class="marca-txt">
        <div class="marca-t">{SISTEMA_NOMBRE}</div>
        <div class="marca-s">Corredor Añelo · Vaca Muerta, Neuquén — caminos de greda y ripio</div>
      </div>
    </div>
    <div class="meta">
      <div><div class="meta-k">Última corrida</div>
        <div class="meta-v">{_e(estado['timestamp_local'].replace('T', ' '))}</div></div>
      <div><div class="meta-k">Antigüedad</div>
        <div class="meta-v" id="frescura" data-ts="{_e(estado['timestamp_local'])}">—</div></div>
      <div><div class="meta-k">Ciclo</div><div class="meta-v">2 h</div></div>
    </div>
  </div>
</header>

<div class="wrap">
  <div class="stale" id="banner-stale" hidden>
    <b>Dato desactualizado.</b> Esta información tiene más de 3 horas: la
    actualización automática puede haberse interrumpido. Verificar el estado real
    antes de tomar una decisión operativa.
  </div>

  <section class="estado" style="--nivel:{COLOR_NIVEL[nivel]}">
    <div class="estado-fila">
      <div class="estado-bloque">
        <span class="estado-ico" aria-hidden="true">{ICONO[nivel]}</span>
        <div>
          <div class="rotulo">Estado del corredor</div>
          <div class="estado-nivel">{ETIQUETA[nivel]}</div>
        </div>
      </div>
      <div class="estado-accion">{_e(estado['accion_recomendada'])}</div>
    </div>
    {_banda_perspectiva(estado)}
  </section>

  <div class="sec"><h2>Puntos de control</h2>
    <span>{len(estado['puntos'])} puntos monitoreados · IIE sobre 100</span></div>
  <div class="tabla-caja">
    <table class="datos">
      <thead><tr>
        <th class="izq">Cód.</th><th class="izq">Punto</th><th>Estado</th><th>IIE</th>
        <th>Lluvia 24 h<br><span style="font-weight:400">mm obs.</span></th>
        <th>Pron. 24 h<br><span style="font-weight:400">mm</span></th>
        <th>Pron. 72 h<br><span style="font-weight:400">mm</span></th>
        <th>Suelo<br><span style="font-weight:400">% sat.</span></th>
        <th>Aviso SMN</th><th>Proyección 72 h</th><th class="izq">Disparadores</th>
      </tr></thead>
      <tbody>{"".join(_fila_punto(p) for p in estado["puntos"])}</tbody>
    </table>
  </div>

  <div class="sec"><h2>Consulta por coordenadas</h2>
    <span>Evaluación puntual en vivo · {len(datos_js['poligonosSmn'])} polígonos SMN cargados</span></div>
  {_panel_consulta()}

  <div class="sec"><h2>Evolución</h2><span>72 h observadas · 72 h pronosticadas</span></div>

  <div class="panel">
    <div class="panel-t">Precipitación acumulada móvil de 24 h</div>
    <div class="panel-s">Milímetros caídos en las 24 h previas a cada hora. Las bandas
      de fondo marcan las zonas de restricción; el tramo con guiones es pronóstico.</div>
    <div class="leyenda">{leyenda}</div>
    <div class="scroll-x"><div id="g-precip"></div></div>
  </div>

  <div class="panel">
    <div class="panel-t">Saturación de humedad del suelo (0-7 cm)</div>
    <div class="panel-s">Porcentaje de saturación sobre porosidad total
      ({config.POROSIDAD_TOTAL} m³/m³). Es la variable que gobierna el barro en greda
      cuando la lluvia ya pasó.</div>
    <div class="leyenda">{leyenda}</div>
    <div class="scroll-x"><div id="g-suelo"></div></div>
  </div>

  <div class="sec"><h2>Avisos oficiales SMN</h2>
    <span>{len(alertas)} vigente(s) sobre los puntos · {_e(estado.get('avisos_cap_pais', 0))} en el país</span></div>
  {bloque_avisos}

  <div class="sec"><h2>Matriz de decisión</h2><span>Regla vigente del sistema</span></div>
  <div class="tabla-caja">
    <table class="matriz">
      <thead><tr><th>Nivel</th><th>Condición</th><th>Acción operativa</th></tr></thead>
      <tbody>
        <tr><td style="color:var(--ok-txt)">● VERDE</td>
          <td>Lluvia &lt; {config.PRECIP_AMARILLO_MM:.0f} mm <b>y</b> saturación &lt; {config.SATURACION_AMARILLO_PCT:.0f} %</td>
          <td>{_e(config.ACCION_POR_NIVEL['verde'])}</td></tr>
        <tr><td style="color:var(--warn-txt)">▲ AMARILLO</td>
          <td>Lluvia {config.PRECIP_AMARILLO_MM:.0f}-{config.PRECIP_ROJO_MM:.0f} mm <b>o</b> saturación {config.SATURACION_AMARILLO_PCT:.0f}-{config.SATURACION_ROJO_PCT:.0f} % <b>o</b> aviso SMN amarillo</td>
          <td>{_e(config.ACCION_POR_NIVEL['amarillo'])}</td></tr>
        <tr><td style="color:var(--crit-txt)">■ ROJO</td>
          <td>Lluvia &gt; {config.PRECIP_ROJO_MM:.0f} mm <b>o</b> saturación &gt; {config.SATURACION_ROJO_PCT:.0f} % <b>o</b> aviso SMN naranja/rojo</td>
          <td>{_e(config.ACCION_POR_NIVEL['rojo'])}</td></tr>
      </tbody>
    </table>
  </div>

  <div class="pie">
    <div><h3>Origen de los datos</h3>
      Variables horarias: <code>api.open-meteo.com</code><br>
      Avisos oficiales: <code>ssl.smn.gob.ar/CAP/AR.php</code><br>
      Feed CAP (Common Alerting Protocol, OASIS/OMM), con verificación
      punto-en-polígono contra las coordenadas de cada punto de control.
    </div>
    <div><h3>Criterios de cálculo</h3>
      <dl>
        <dt>Lluvia de referencia</dt><dd>máx(obs. 24 h, pron. 24 h)</dd>
        <dt>Porosidad de suelo</dt><dd>{config.POROSIDAD_TOTAL} m³/m³</dd>
        <dt>Umbral amarillo</dt><dd>{config.SATURACION_AMARILLO_PCT / 100 * config.POROSIDAD_TOTAL:.3f} m³/m³</dd>
        <dt>Umbral rojo</dt><dd>{config.SATURACION_ROJO_PCT / 100 * config.POROSIDAD_TOTAL:.3f} m³/m³</dd>
        <dt>Buffer de aviso</dt><dd>{config.BUFFER_ALERTA_GRADOS}° (~2 km)</dd>
      </dl>
    </div>
    <div><h3>Operación del sistema</h3>
      <dl>
        <dt>Versión</dt><dd>{VERSION}</dd>
        <dt>Ciclo de corrida</dt><dd>cada 2 h</dd>
        <dt>Recarga de página</dt><dd>cada 30 min</dd>
        <dt>Alerta de dato viejo</dt><dd>&gt; 3 h</dd>
        <dt>Puntos con error</dt><dd>{len(estado.get('puntos_con_error', [])) or 'ninguno'}</dd>
      </dl>
    </div>
    <div><h3>Alcance</h3>
      Sistema de apoyo a la decisión operativa. La resolución de los modelos
      meteorológicos es de aproximadamente 9 km: sirve para decidir a nivel
      corredor, no para un tramo puntual. El criterio del responsable de
      operaciones prevalece sobre el semáforo.
    </div>
  </div>
</div>
<div class="tip" id="tip" role="status" aria-live="polite"></div>
<script>window.__DATOS__ = {json.dumps(datos_js, ensure_ascii=False)};</script>
<script>{JS}</script>"""


def generar(estado: Dict[str, Any],
            series: Dict[str, Dict[str, Any]],
            avisos: Optional[List[Dict[str, Any]]] = None) -> str:
    """Escribe docs/index.html (documento completo, para GitHub Pages)."""
    cuerpo = construir_cuerpo(estado, series, avisos)
    doc = ('<!doctype html>\n<html lang="es-AR">\n<head>\n'
           '<meta charset="utf-8">\n'
           '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
           '<meta http-equiv="refresh" content="1800">\n'
           '<meta name="robots" content="noindex, nofollow">\n'
           '<meta name="description" content="Estado de transitabilidad de caminos '
           'de greda en el corredor Añelo, Vaca Muerta.">\n'
           f'<title>{SISTEMA_SIGLA} — Corredor Añelo</title>\n'
           '</head>\n<body>\n' + cuerpo + '\n</body>\n</html>\n')
    os.makedirs(config.DIR_DOCS, exist_ok=True)
    with open(config.HTML_TABLERO, "w", encoding="utf-8") as f:
        f.write(doc)
    log.info("Tablero -> %s (%d KB)", config.HTML_TABLERO, len(doc) // 1024)
    return doc
