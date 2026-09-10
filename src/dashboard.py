"""
Generador del tablero HTML estático (GitHub Pages, costo cero).

Produce un documento autocontenido: sin CDNs, sin dependencias, sin llamadas de
red desde el navegador. Los datos van embebidos como JSON en la propia página,
de modo que el archivo funciona incluso abierto localmente desde el disco.

Complementa a Power BI: es la vista de guardia, siempre accesible desde el
celular en el yacimiento y sin licencia.
"""

from __future__ import annotations

import html
import json
import logging
import os
from typing import Any, Dict, List, Optional, Optional

from datetime import datetime

from . import config
from .iie import saturacion_pct

log = logging.getLogger(__name__)

ICONO = {"verde": "●", "amarillo": "▲", "rojo": "■"}
ETIQUETA = {"verde": "VERDE", "amarillo": "AMARILLO", "rojo": "ROJO"}

# Slots categóricos 1-3 (validados all-pairs en ambos modos)
SERIE_COLORES = ["#2a78d6", "#eb6834", "#1baf7a"]
SERIE_COLORES_DARK = ["#3987e5", "#d95926", "#199e70"]


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
    for i, (punto_id, datos) in enumerate(series.items()):
        horas = [p["hora"] for p in datos["serie_horaria"]]
        precip = [p["precipitacion_mm"] for p in datos["serie_horaria"]]
        suelo = [p["humedad_suelo_m3m3"] for p in datos["serie_horaria"]]
        pron = [p["es_pronostico"] for p in datos["serie_horaria"]]
        salida.append({
            "id": punto_id,
            "nombre": datos["punto_nombre"],
            "color": SERIE_COLORES[i % len(SERIE_COLORES)],
            "colorDark": SERIE_COLORES_DARK[i % len(SERIE_COLORES_DARK)],
            "horas": horas,
            "precip24": _rolling_24h(precip),
            "saturacion": [saturacion_pct(v) for v in suelo],
            "esPronostico": pron,
        })
    return salida


# --------------------------------------------------------------------------- #
# CSS
# --------------------------------------------------------------------------- #

CSS = """
:root{
  color-scheme: light;
  --surface-1:#fcfcfb; --plane:#f9f9f7;
  --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --hairline:rgba(11,11,11,.10);
  --good:#0ca30c; --warning:#fab219; --critical:#d03b3b;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a;
  --chip-verde-bg:rgba(12,163,12,.12); --chip-amarillo-bg:rgba(250,178,25,.18);
  --chip-rojo-bg:rgba(208,59,59,.14);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme: dark;
    --surface-1:#1a1a19; --plane:#0d0d0d;
    --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --hairline:rgba(255,255,255,.10);
    --s1:#3987e5; --s2:#d95926; --s3:#199e70;
    --chip-verde-bg:rgba(12,163,12,.18); --chip-amarillo-bg:rgba(250,178,25,.16);
    --chip-rojo-bg:rgba(208,59,59,.20);
  }
}
:root[data-theme="dark"]{
  color-scheme: dark;
  --surface-1:#1a1a19; --plane:#0d0d0d;
  --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --hairline:rgba(255,255,255,.10);
  --s1:#3987e5; --s2:#d95926; --s3:#199e70;
  --chip-verde-bg:rgba(12,163,12,.18); --chip-amarillo-bg:rgba(250,178,25,.16);
  --chip-rojo-bg:rgba(208,59,59,.20);
}

*{box-sizing:border-box}
body{
  margin:0; background:var(--plane); color:var(--ink);
  font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1180px; margin:0 auto; padding:28px 20px 64px}

/* ---------- Encabezado ---------- */
.top{display:flex; flex-wrap:wrap; gap:16px; align-items:flex-end; justify-content:space-between; margin-bottom:6px}
h1{font-size:20px; font-weight:650; margin:0; letter-spacing:-.01em}
.sub{color:var(--ink-2); font-size:13px; margin:4px 0 0}
.stamp{color:var(--muted); font-size:12px; font-variant-numeric:tabular-nums; text-align:right}

/* ---------- Hero de estado ---------- */
.hero{
  margin:20px 0 26px; padding:20px 22px; border-radius:12px;
  background:var(--surface-1); border:1px solid var(--hairline);
  border-left:5px solid var(--nivel-color); display:flex; flex-wrap:wrap;
  gap:20px; align-items:center; justify-content:space-between;
}
.hero-l{display:flex; align-items:center; gap:16px; min-width:0}
.hero-icon{font-size:26px; line-height:1; color:var(--nivel-color)}
.hero-k{font-size:11px; letter-spacing:.09em; text-transform:uppercase; color:var(--muted); margin-bottom:2px}
.hero-v{font-size:28px; font-weight:680; letter-spacing:-.02em; line-height:1.1}
.hero-accion{color:var(--ink-2); font-size:13.5px; max-width:520px}

/* ---------- Tarjetas por punto ---------- */
.grid{display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:14px; margin-bottom:30px}
.card{background:var(--surface-1); border:1px solid var(--hairline); border-radius:10px; padding:16px 17px}
.card-top{display:flex; align-items:flex-start; justify-content:space-between; gap:10px; margin-bottom:2px}
.card-n{font-size:15px; font-weight:620; letter-spacing:-.01em}
.card-d{font-size:12px; color:var(--muted); margin-bottom:14px}
.chip{
  display:inline-flex; align-items:center; gap:5px; padding:3px 9px; border-radius:999px;
  font-size:11px; font-weight:660; letter-spacing:.05em; white-space:nowrap;
}
.chip-verde{background:var(--chip-verde-bg); color:var(--good)}
.chip-amarillo{background:var(--chip-amarillo-bg); color:#8a5d00}
:root:not([data-theme="light"]) .chip-amarillo{color:var(--warning)}
@media (prefers-color-scheme: light){:root:not([data-theme="dark"]) .chip-amarillo{color:#8a5d00}}
:root[data-theme="dark"] .chip-amarillo{color:var(--warning)}
.chip-rojo{background:var(--chip-rojo-bg); color:var(--critical)}

.iie-row{display:flex; align-items:baseline; gap:8px; margin-bottom:10px}
.iie-v{font-size:30px; font-weight:680; letter-spacing:-.02em; line-height:1}
.iie-l{font-size:11px; color:var(--muted); letter-spacing:.06em; text-transform:uppercase}
.meter{height:6px; border-radius:3px; background:var(--grid); overflow:hidden; margin-bottom:14px}
.meter i{display:block; height:100%; border-radius:3px; background:var(--nivel-color)}

.kv{display:grid; grid-template-columns:1fr auto; gap:5px 12px; font-size:12.5px; padding-top:12px; border-top:1px solid var(--hairline)}
.kv dt{color:var(--ink-2)}
.kv dd{margin:0; font-variant-numeric:tabular-nums; font-weight:560; text-align:right}
.trig{margin:12px 0 0; padding:0; list-style:none; font-size:12px; color:var(--ink-2)}
.trig li{padding-left:13px; position:relative; margin-bottom:3px}
.trig li::before{content:"·"; position:absolute; left:4px; color:var(--muted)}

.outlook{
  display:flex; gap:9px; align-items:flex-start; margin-top:13px; padding:9px 11px;
  border-radius:8px; border:1px dashed var(--nivel-color); font-size:12px;
  color:var(--ink-2); line-height:1.45;
}
.outlook span{color:var(--nivel-color); font-size:13px; line-height:1.35}
.outlook strong{color:var(--ink); font-weight:640}

.hero-out{
  width:100%; margin-top:4px; padding:11px 14px; border-radius:8px;
  border:1px dashed var(--pron-color); font-size:13px; color:var(--ink-2);
  display:flex; gap:9px; align-items:center;
}
.hero-out b{color:var(--ink); font-weight:640}
.hero-out span{color:var(--pron-color); font-size:15px}

/* ---------- Gráficos ---------- */
.chart-card{background:var(--surface-1); border:1px solid var(--hairline); border-radius:10px; padding:18px 18px 12px; margin-bottom:14px}
.chart-h{margin-bottom:2px; font-size:14.5px; font-weight:620}
.chart-s{font-size:12px; color:var(--ink-2); margin-bottom:14px}
.legend{display:flex; flex-wrap:wrap; gap:14px; margin-bottom:12px; font-size:12px; color:var(--ink-2)}
.legend span{display:inline-flex; align-items:center; gap:6px}
.swatch{width:14px; height:2.5px; border-radius:2px; display:inline-block}
.chart-scroll{overflow-x:auto}
svg{display:block; width:100%; height:auto}
.tip{
  position:fixed; pointer-events:none; z-index:20; opacity:0; transition:opacity .1s;
  background:var(--surface-1); border:1px solid var(--hairline); border-radius:8px;
  padding:9px 11px; font-size:12px; box-shadow:0 6px 20px rgba(0,0,0,.14); min-width:170px;
}
.tip b{display:block; font-size:11.5px; color:var(--ink-2); font-weight:560; margin-bottom:6px}
.tip .r{display:flex; align-items:center; gap:7px; justify-content:space-between; margin-top:3px}
.tip .r em{font-style:normal; color:var(--ink-2); display:flex; align-items:center; gap:6px}
.tip .r strong{font-variant-numeric:tabular-nums; font-weight:620}

/* ---------- Tabla ---------- */
details{background:var(--surface-1); border:1px solid var(--hairline); border-radius:10px; padding:14px 18px; margin-bottom:14px}
summary{cursor:pointer; font-size:13.5px; font-weight:600}
table{width:100%; border-collapse:collapse; margin-top:14px; font-size:12.5px}
th,td{text-align:right; padding:7px 8px; border-bottom:1px solid var(--hairline); font-variant-numeric:tabular-nums}
th:first-child,td:first-child{text-align:left; font-variant-numeric:normal}
th{color:var(--muted); font-weight:560; font-size:11px; letter-spacing:.05em; text-transform:uppercase}

/* ---------- Alertas SMN ---------- */
.alerta{border-left:3px solid var(--warning); padding:10px 14px; margin-bottom:9px; background:var(--surface-1); border-radius:0 8px 8px 0; border-top:1px solid var(--hairline); border-right:1px solid var(--hairline); border-bottom:1px solid var(--hairline)}
.alerta.naranja{border-left-color:#ec835a}
.alerta.rojo{border-left-color:var(--critical)}
.alerta h4{margin:0 0 3px; font-size:13px; font-weight:620}
.alerta p{margin:0; font-size:12.5px; color:var(--ink-2)}
.alerta .meta{font-size:11.5px; color:var(--muted); margin-top:5px; font-variant-numeric:tabular-nums}

.stale{
  background:var(--chip-rojo-bg); border:1px solid var(--critical); color:var(--ink);
  border-radius:8px; padding:12px 15px; margin-bottom:18px; font-size:13px; line-height:1.5;
}
h2{font-size:13px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); font-weight:600; margin:32px 0 12px}
footer{margin-top:36px; padding-top:16px; border-top:1px solid var(--hairline); font-size:11.5px; color:var(--muted); line-height:1.7}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:11.5px; background:var(--grid); padding:1px 5px; border-radius:4px}
@media(max-width:640px){ .wrap{padding:18px 14px 48px} .hero-v{font-size:24px} h1{font-size:17px} }
"""


# --------------------------------------------------------------------------- #
# JS de los gráficos (SVG puro, sin librerías)
# --------------------------------------------------------------------------- #

JS = r"""
(function(){
  const D = window.__DATOS__;
  const dark = () => document.documentElement.dataset.theme === 'dark'
    || (document.documentElement.dataset.theme !== 'light'
        && matchMedia('(prefers-color-scheme: dark)').matches);
  const col = s => dark() ? s.colorDark : s.color;
  const css = v => getComputedStyle(document.body).getPropertyValue(v).trim();

  const NS='http://www.w3.org/2000/svg';
  const el=(n,a={})=>{const e=document.createElementNS(NS,n);
    for(const k in a) e.setAttribute(k,a[k]); return e;};

  const tip = document.getElementById('tip');

  function fmtHora(iso){
    const d=new Date(iso);
    const dias=['dom','lun','mar','mié','jue','vie','sáb'];
    return dias[d.getDay()]+' '+String(d.getDate()).padStart(2,'0')+'/'
      +String(d.getMonth()+1).padStart(2,'0')+' '+String(d.getHours()).padStart(2,'0')+':00';
  }

  function dibujar(cfg){
    const host=document.getElementById(cfg.id);
    if(!host) return;
    host.innerHTML='';

    const W=940, H=cfg.alto||250, m={t:14,r:118,b:30,l:46};
    const iw=W-m.l-m.r, ih=H-m.t-m.b;
    const n=D.series[0][cfg.campo].length;
    const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,role:'img',
      'aria-label':cfg.aria,preserveAspectRatio:'xMidYMid meet'});

    let max=0;
    D.series.forEach(s=>s[cfg.campo].forEach(v=>{if(v!=null&&v>max)max=v;}));
    cfg.umbrales.forEach(u=>{if(u.v>max)max=u.v;});
    max = cfg.max != null ? cfg.max : (max*1.18||1);

    const x=i=>m.l+(i/(n-1))*iw;
    const y=v=>m.t+ih-(v/max)*ih;

    // --- grilla + eje Y ---
    const pasos=4;
    for(let k=0;k<=pasos;k++){
      const v=max*k/pasos, yy=y(v);
      svg.appendChild(el('line',{x1:m.l,x2:m.l+iw,y1:yy,y2:yy,
        stroke:css('--grid'),'stroke-width':1}));
      const t=el('text',{x:m.l-9,y:yy+4,'text-anchor':'end',
        fill:css('--muted'),'font-size':11,'font-family':'system-ui,sans-serif'});
      t.textContent=(max>=20?Math.round(v):v.toFixed(1));
      svg.appendChild(t);
    }

    // --- umbrales de la matriz de riesgo ---
    cfg.umbrales.forEach(u=>{
      svg.appendChild(el('line',{x1:m.l,x2:m.l+iw,y1:y(u.v),y2:y(u.v),
        stroke:u.color,'stroke-width':1.5,'stroke-dasharray':'5 4','opacity':.72}));
      const t=el('text',{x:m.l+iw+7,y:y(u.v)+3.5,fill:u.color,'font-size':10.5,
        'font-weight':600,'font-family':'system-ui,sans-serif'});
      t.textContent=u.etiqueta;
      svg.appendChild(t);
    });

    // --- separador observado / pronóstico ---
    const iAhora=D.series[0].esPronostico.findIndex(p=>p);
    if(iAhora>0){
      const xa=x(iAhora);
      svg.appendChild(el('line',{x1:xa,x2:xa,y1:m.t,y2:m.t+ih,
        stroke:css('--axis'),'stroke-width':1.5,'stroke-dasharray':'2 3'}));
      const t=el('text',{x:xa+5,y:m.t+11,fill:css('--muted'),'font-size':10,
        'font-family':'system-ui,sans-serif'});
      t.textContent='ahora →';
      svg.appendChild(t);
    }

    // --- eje X ---
    for(let i=0;i<n;i+=24){
      const t=el('text',{x:x(i),y:H-9,'text-anchor':'middle',fill:css('--muted'),
        'font-size':11,'font-family':'system-ui,sans-serif'});
      const d=new Date(D.series[0].horas[i]);
      t.textContent=String(d.getDate()).padStart(2,'0')+'/'+String(d.getMonth()+1).padStart(2,'0');
      svg.appendChild(t);
    }
    svg.appendChild(el('line',{x1:m.l,x2:m.l+iw,y1:m.t+ih,y2:m.t+ih,
      stroke:css('--axis'),'stroke-width':1}));

    // --- series (2px, tramo pronosticado punteado) ---
    // Las etiquetas directas se colocan al final evitando solapamiento vertical.
    const etiquetas=[];
    D.series.forEach(s=>{
      const v=s[cfg.campo];
      const seg=(desde,hasta,dash)=>{
        let d='';
        for(let i=desde;i<=hasta;i++){
          if(v[i]==null) continue;
          d+=(d?'L':'M')+x(i).toFixed(1)+' '+y(v[i]).toFixed(1);
        }
        if(!d) return;
        const p=el('path',{d,fill:'none',stroke:col(s),'stroke-width':2,
          'stroke-linecap':'round','stroke-linejoin':'round'});
        if(dash) p.setAttribute('stroke-dasharray','4 3.5');
        svg.appendChild(p);
      };
      const corte=iAhora>0?iAhora:n-1;
      seg(0,corte,false);
      seg(corte,n-1,true);

      // etiqueta directa al final (requerida: aqua queda bajo 3:1 en claro)
      let ult=n-1; while(ult>0&&v[ult]==null) ult--;
      if(v[ult]!=null) etiquetas.push({y:y(v[ult]),color:col(s),texto:s.nombre.split(' ')[0]});
    });

    // Anti-colisión: separa las etiquetas al menos 13 px en vertical
    etiquetas.sort((a,b)=>a.y-b.y);
    for(let i=1;i<etiquetas.length;i++){
      if(etiquetas[i].y-etiquetas[i-1].y<13) etiquetas[i].y=etiquetas[i-1].y+13;
    }
    const exceso=etiquetas.length?Math.max(0,etiquetas[etiquetas.length-1].y-(m.t+ih)):0;
    etiquetas.forEach(e=>{
      const t=el('text',{x:m.l+iw+7,y:e.y-exceso+4,fill:e.color,'font-size':11,
        'font-weight':620,'font-family':'system-ui,sans-serif'});
      t.textContent=e.texto;
      svg.appendChild(t);
    });

    // --- capa de hover: crosshair + tooltip ---
    const cross=el('line',{x1:0,x2:0,y1:m.t,y2:m.t+ih,stroke:css('--axis'),
      'stroke-width':1,opacity:0});
    svg.appendChild(cross);
    const pts=D.series.map(s=>{
      const c=el('circle',{r:4.5,fill:col(s),stroke:css('--surface-1'),
        'stroke-width':2,opacity:0});
      svg.appendChild(c); return c;
    });
    const hit=el('rect',{x:m.l,y:m.t,width:iw,height:ih,fill:'transparent'});
    svg.appendChild(hit);

    function mover(ev){
      const r=svg.getBoundingClientRect();
      const px=(ev.touches?ev.touches[0].clientX:ev.clientX)-r.left;
      const i=Math.max(0,Math.min(n-1,Math.round(((px/r.width*W)-m.l)/iw*(n-1))));
      cross.setAttribute('x1',x(i)); cross.setAttribute('x2',x(i));
      cross.setAttribute('opacity',.85);
      let filas='';
      D.series.forEach((s,k)=>{
        const v=s[cfg.campo][i];
        if(v==null){pts[k].setAttribute('opacity',0); return;}
        pts[k].setAttribute('cx',x(i)); pts[k].setAttribute('cy',y(v));
        pts[k].setAttribute('opacity',1);
        filas+=`<div class="r"><em><span class="swatch" style="background:${col(s)}"></span>${s.nombre}</em><strong>${v.toFixed(1)}${cfg.unidad}</strong></div>`;
      });
      const pron=D.series[0].esPronostico[i];
      tip.innerHTML=`<b>${fmtHora(D.series[0].horas[i])} · ${pron?'pronóstico':'observado'}</b>${filas}`;
      tip.style.opacity=1;
      const cx=(ev.touches?ev.touches[0].clientX:ev.clientX);
      const cy=(ev.touches?ev.touches[0].clientY:ev.clientY);
      const tw=tip.offsetWidth;
      tip.style.left=Math.min(window.innerWidth-tw-10,Math.max(8,cx+14))+'px';
      tip.style.top=Math.max(8,cy-tip.offsetHeight-12)+'px';
    }
    function salir(){
      tip.style.opacity=0; cross.setAttribute('opacity',0);
      pts.forEach(p=>p.setAttribute('opacity',0));
    }
    hit.addEventListener('mousemove',mover);
    hit.addEventListener('mouseleave',salir);
    hit.addEventListener('touchmove',e=>{mover(e);e.preventDefault();},{passive:false});
    hit.addEventListener('touchend',salir);

    host.appendChild(svg);
  }

  function todo(){
    dibujar({
      id:'g-precip', campo:'precip24', unidad:' mm', alto:250,
      aria:'Precipitación acumulada móvil de 24 horas por punto crítico',
      umbrales:[
        {v:D.umbrales.precipAmarillo,etiqueta:'3 mm · amarillo',color:css('--warning')},
        {v:D.umbrales.precipRojo,etiqueta:'7 mm · rojo',color:css('--critical')}
      ]
    });
    dibujar({
      id:'g-suelo', campo:'saturacion', unidad:' %', alto:250, max:100,
      aria:'Saturación de humedad del suelo por punto crítico',
      umbrales:[
        {v:D.umbrales.satAmarillo,etiqueta:'60 % · amarillo',color:css('--warning')},
        {v:D.umbrales.satRojo,etiqueta:'75 % · rojo',color:css('--critical')}
      ]
    });
  }

  todo();
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change',todo);
  let t; addEventListener('resize',()=>{clearTimeout(t);t=setTimeout(todo,180);});

  // --- Indicador de frescura ---------------------------------------------
  // Si el workflow se rompe, la página sigue mostrando el último dato bueno y
  // nadie se entera. Este cartel hace visible el dato viejo: es la diferencia
  // entre un tablero confiable y uno peligroso.
  function frescura(){
    const el=document.getElementById('frescura');
    if(!el) return;
    const ts=new Date(el.dataset.ts+'-03:00');
    if(isNaN(ts)) return;
    const min=Math.floor((Date.now()-ts.getTime())/60000);
    let txt, alerta=false;
    if(min<0)        txt='Próxima corrida en ≤ 2 h';
    else if(min<90)  txt='hace '+min+' min';
    else if(min<180) txt='hace '+Math.floor(min/60)+' h '+(min%60)+' min';
    else { txt='DATO DESACTUALIZADO · hace '+Math.floor(min/60)+' h'; alerta=true; }
    el.textContent=txt;
    el.style.color = alerta ? css('--critical') : '';
    el.style.fontWeight = alerta ? '700' : '';
    // Con corridas cada 2 h, pasadas 3 h algo falló: el cron, la API o el commit.
    const b=document.getElementById('banner-stale');
    if(b) b.hidden = !alerta;
  }
  frescura();
  setInterval(frescura, 60000);
})();
"""


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #

def _e(x: Any) -> str:
    return html.escape("" if x is None else str(x))


def _n(v: Any, dec: int = 1, suf: str = "") -> str:
    if v is None or v == "":
        return "s/d"
    try:
        return f"{float(v):.{dec}f}{suf}"
    except (TypeError, ValueError):
        return _e(v)


COLOR_NIVEL = {"verde": "var(--good)", "amarillo": "var(--warning)", "rojo": "var(--critical)"}


def _fmt_hora(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    try:
        d = datetime.fromisoformat(iso)
        return f"{d.day:02d}/{d.month:02d} {d.hour:02d}:00"
    except ValueError:
        return _e(iso)


def _tarjeta(p: Dict[str, Any]) -> str:
    nivel = p["nivel"]
    trig = "".join(f"<li>{_e(d)}</li>" for d in p.get("disparadores", []))

    pron = p.get("nivel_pronosticado", "verde")
    aviso = ""
    if config.ORDEN_NIVELES.get(pron, 0) > config.ORDEN_NIVELES.get(nivel, 0):
        horas = p.get("horas_hasta_pico")
        anticipo = f" (en ~{horas} h)" if horas else ""
        aviso = (
            '<div class="outlook" style="--nivel-color:{c}">'
            '<span aria-hidden="true">{i}</span>'
            '<div><strong>Escalaría a {n}</strong> el {h} h — pico de '
            '{mm} en 24 h{a}.</div></div>'
        ).format(
            c=COLOR_NIVEL[pron], i=ICONO[pron], n=ETIQUETA[pron],
            h=_fmt_hora(p.get("hora_pico")),
            mm=_n(p.get("pico_precip_24h_mm"), 1, " mm"), a=anticipo,
        )
    return f"""
<article class="card" style="--nivel-color:{COLOR_NIVEL[nivel]}">
  <div class="card-top">
    <div>
      <div class="card-n">{_e(p['punto_nombre'])}</div>
      <div class="card-d">{_e(p.get('lat'))}, {_e(p.get('lon'))}</div>
    </div>
    <span class="chip chip-{nivel}">{ICONO[nivel]} {ETIQUETA[nivel]}</span>
  </div>
  <div class="iie-row"><span class="iie-v">{_n(p['iie'], 0)}</span><span class="iie-l">IIE / 100</span></div>
  <div class="meter"><i style="width:{max(2, min(100, float(p['iie'] or 0)))}%"></i></div>
  <dl class="kv">
    <dt>Lluvia de referencia</dt><dd>{_n(p['precip_referencia_mm'], 1, ' mm')}</dd>
    <dt>Acumulado 24 h</dt><dd>{_n(p['precip_acum_24h_mm'], 1, ' mm')}</dd>
    <dt>Pronóstico 24 h</dt><dd>{_n(p['precip_pron_24h_mm'], 1, ' mm')}</dd>
    <dt>Pronóstico 72 h</dt><dd>{_n(p['precip_pron_72h_mm'], 1, ' mm')}</dd>
    <dt>Saturación de suelo</dt><dd>{_n(p['saturacion_suelo_pct'], 0, ' %')}</dd>
    <dt>Alerta SMN</dt><dd>{_e(p['alerta_smn_color'].upper() if p.get('alerta_smn_color') else '—')}</dd>
  </dl>
  <ul class="trig">{trig}</ul>
  {aviso}
</article>"""


def _fila_tabla(p: Dict[str, Any]) -> str:
    return f"""<tr>
  <td>{_e(p['punto_nombre'])}</td>
  <td>{ICONO[p['nivel']]} {ETIQUETA[p['nivel']]}</td>
  <td>{_n(p['iie'], 0)}</td>
  <td>{_n(p['precip_acum_24h_mm'], 1)}</td>
  <td>{_n(p['precip_pron_24h_mm'], 1)}</td>
  <td>{_n(p['precip_pron_72h_mm'], 1)}</td>
  <td>{_n(p['humedad_suelo_m3m3'], 3)}</td>
  <td>{_n(p['saturacion_suelo_pct'], 0)}</td>
</tr>"""


def _alerta(a: Dict[str, Any]) -> str:
    color = a.get("color_smn", "amarillo")
    return f"""
<div class="alerta {color}">
  <h4>{_e(a.get('evento'))} — SMN {color.upper()}</h4>
  <p>{_e(a.get('descripcion'))}</p>
  <div class="meta">Vigencia: {_e(a.get('inicio'))} → {_e(a.get('expira'))} · severidad CAP {_e(a.get('severidad_cap'))} · certeza {_e(a.get('certeza'))}</div>
</div>"""


def _hero_outlook(estado: Dict[str, Any]) -> str:
    """Franja de anticipación: qué va a pasar en las próximas 72 h."""
    actual = estado["nivel_consolidado"]
    peor = max(
        (p.get("nivel_pronosticado", "verde") for p in estado["puntos"]),
        key=lambda n: config.ORDEN_NIVELES.get(n, 0),
        default="verde",
    )
    if config.ORDEN_NIVELES.get(peor, 0) <= config.ORDEN_NIVELES.get(actual, 0):
        return (
            '<div class="hero-out" style="--pron-color:var(--good)">'
            '<span aria-hidden="true">●</span>'
            '<div>Perspectiva 72 h: <b>sin deterioro previsto</b>. '
            'Ningún punto supera los umbrales con el pronóstico vigente.</div></div>'
        )

    criticos = [p for p in estado["puntos"] if p.get("nivel_pronosticado") == peor]
    primero = min(
        criticos, key=lambda p: p.get("horas_hasta_pico") or 999
    )
    nombres = ", ".join(p["punto_nombre"] for p in criticos)
    return (
        '<div class="hero-out" style="--pron-color:{c}">'
        '<span aria-hidden="true">{i}</span>'
        '<div>Perspectiva 72 h: <b>escalada a {n}</b> en {puntos} — '
        'pico previsto el {h} h ({mm} en 24 h). '
        'Ventana de anticipación: ~{horas} h.</div></div>'
    ).format(
        c=COLOR_NIVEL[peor], i=ICONO[peor], n=ETIQUETA[peor], puntos=_e(nombres),
        h=_fmt_hora(primero.get("hora_pico")),
        mm=_n(primero.get("pico_precip_24h_mm"), 1, " mm"),
        horas=primero.get("horas_hasta_pico") or "—",
    )


def construir_cuerpo(estado: Dict[str, Any], series: Dict[str, Dict[str, Any]]) -> str:
    """Devuelve <style> + markup + <script>, sin doctype/head/body."""
    nivel = estado["nivel_consolidado"]
    datos_js = {
        "series": preparar_series(series),
        "umbrales": {
            "precipAmarillo": config.PRECIP_AMARILLO_MM,
            "precipRojo": config.PRECIP_ROJO_MM,
            "satAmarillo": config.SATURACION_AMARILLO_PCT,
            "satRojo": config.SATURACION_ROJO_PCT,
        },
    }

    alertas = estado.get("alertas_smn_vigentes_zona", [])
    bloque_alertas = (
        "".join(_alerta(a) for a in alertas)
        if alertas else
        '<div class="alerta" style="border-left-color:var(--good)">'
        '<h4>Sin alertas SMN vigentes sobre los puntos críticos</h4>'
        '<p>No hay avisos del Servicio Meteorológico Nacional cuyo polígono '
        'contenga las coordenadas monitoreadas.</p></div>'
    )

    leyenda = "".join(
        f'<span><i class="swatch" style="background:{s["color"]}"></i>{_e(s["nombre"])}</span>'
        for s in datos_js["series"]
    )

    return f"""<style>{CSS}</style>
<div class="wrap">
  <div class="stale" id="banner-stale" hidden>
    <strong>Atención:</strong> estos datos tienen más de 3 horas. La actualización
    automática puede haberse interrumpido — verificar antes de tomar una decisión
    operativa con esta información.
  </div>
  <div class="top">
    <div>
      <h1>Alerta temprana de anegamiento de caminos</h1>
      <p class="sub">Añelo — Vaca Muerta, Neuquén · caminos de greda y ripio</p>
    </div>
    <div class="stamp">
      Actualizado<br>{_e(estado['timestamp_local'].replace('T', ' '))} (ART)<br>
      <span id="frescura" data-ts="{_e(estado['timestamp_local'])}">Próxima corrida en ≤ 2 h</span>
    </div>
  </div>

  <section class="hero" style="--nivel-color:{COLOR_NIVEL[nivel]}">
    <div class="hero-l">
      <span class="hero-icon" aria-hidden="true">{ICONO[nivel]}</span>
      <div>
        <div class="hero-k">Estado del corredor</div>
        <div class="hero-v" style="color:{COLOR_NIVEL[nivel]}">{ETIQUETA[nivel]}</div>
      </div>
    </div>
    <p class="hero-accion">{_e(estado['accion_recomendada'])}</p>
    {_hero_outlook(estado)}
  </section>

  <h2>Puntos críticos</h2>
  <div class="grid">{"".join(_tarjeta(p) for p in estado["puntos"])}</div>

  <h2>Evolución 72 h atrás / 72 h adelante</h2>

  <div class="chart-card">
    <div class="chart-h">Precipitación acumulada móvil de 24 h</div>
    <div class="chart-s">Milímetros caídos en las 24 h previas a cada hora. Las líneas
      punteadas marcan los umbrales de la matriz de riesgo; el tramo con guiones es pronóstico.</div>
    <div class="legend">{leyenda}</div>
    <div class="chart-scroll"><div id="g-precip"></div></div>
  </div>

  <div class="chart-card">
    <div class="chart-h">Saturación de humedad del suelo (0-7 cm)</div>
    <div class="chart-s">Porcentaje de saturación sobre porosidad total
      ({config.POROSIDAD_TOTAL} m³/m³). Es la variable que gobierna el barro en greda
      cuando la lluvia ya pasó.</div>
    <div class="legend">{leyenda}</div>
    <div class="chart-scroll"><div id="g-suelo"></div></div>
  </div>

  <details>
    <summary>Ver datos en tabla</summary>
    <div class="chart-scroll"><table>
      <thead><tr>
        <th>Punto</th><th>Nivel</th><th>IIE</th><th>Ac. 24 h (mm)</th>
        <th>Pron. 24 h (mm)</th><th>Pron. 72 h (mm)</th>
        <th>Suelo (m³/m³)</th><th>Saturación (%)</th>
      </tr></thead>
      <tbody>{"".join(_fila_tabla(p) for p in estado["puntos"])}</tbody>
    </table></div>
  </details>

  <h2>Alertas oficiales SMN sobre los puntos</h2>
  {bloque_alertas}

  <footer>
    <strong>Matriz de riesgo.</strong>
    Verde: lluvia &lt; {config.PRECIP_AMARILLO_MM:.0f} mm y saturación &lt; {config.SATURACION_AMARILLO_PCT:.0f} %.
    Amarillo: lluvia {config.PRECIP_AMARILLO_MM:.0f}-{config.PRECIP_ROJO_MM:.0f} mm o saturación {config.SATURACION_AMARILLO_PCT:.0f}-{config.SATURACION_ROJO_PCT:.0f} %.
    Rojo: lluvia &gt; {config.PRECIP_ROJO_MM:.0f} mm, saturación &gt; {config.SATURACION_ROJO_PCT:.0f} % o alerta SMN naranja/roja vigente.<br>
    <strong>Lluvia de referencia:</strong> máximo entre el acumulado de las últimas 24 h y el pronóstico de las próximas 24 h.<br>
    <strong>Fuentes:</strong> Open-Meteo (variables horarias, sin API key) ·
    Servicio Meteorológico Nacional, feed CAP oficial <code>ssl.smn.gob.ar/CAP/AR.php</code>.
    {_e(estado.get('avisos_cap_pais', 0))} avisos vigentes en el país al momento de la corrida.<br>
    Actualización automática cada 2 h vía GitHub Actions. Infraestructura de costo cero.
  </footer>
</div>
<div class="tip" id="tip" role="status" aria-live="polite"></div>
<script>window.__DATOS__ = {json.dumps(datos_js, ensure_ascii=False)};</script>
<script>{JS}</script>"""


def generar(estado: Dict[str, Any], series: Dict[str, Dict[str, Any]]) -> str:
    """Escribe docs/index.html (documento completo, para GitHub Pages)."""
    cuerpo = construir_cuerpo(estado, series)
    doc = (
        "<!doctype html>\n<html lang=\"es-AR\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        # Recarga cada 30 min: los datos cambian cada 2 h, así que esto no
        # agrega carga a ninguna API (la página es estática, ya generada) y
        # evita que quede una pestaña abierta mostrando el estado de ayer.
        "<meta http-equiv=\"refresh\" content=\"1800\">\n"
        "<meta name=\"robots\" content=\"noindex, nofollow\">\n"
        "<title>Alerta de anegamiento — Añelo</title>\n"
        "<meta name=\"description\" content=\"Semáforo de transitabilidad de caminos "
        "de greda en Añelo, Vaca Muerta.\">\n"
        "</head>\n<body>\n" + cuerpo + "\n</body>\n</html>\n"
    )
    os.makedirs(config.DIR_DOCS, exist_ok=True)
    with open(config.HTML_TABLERO, "w", encoding="utf-8") as f:
        f.write(doc)
    log.info("Tablero -> %s", config.HTML_TABLERO)
    return doc
