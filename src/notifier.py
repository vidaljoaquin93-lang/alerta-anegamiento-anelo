"""
Notificaciones a Microsoft Teams y/o Telegram.

DESACTIVADO POR DEFECTO. Si el secret correspondiente no está cargado, este
módulo no hace nada y no falla la corrida. Para activarlo, cargar en
Settings > Secrets and variables > Actions:

  TEAMS_WEBHOOK_URL      (Power Automate / Incoming Webhook del canal)
  TELEGRAM_BOT_TOKEN     (token de @BotFather)
  TELEGRAM_CHAT_ID       (id del chat o del grupo)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from . import config
from .http_client import get_session

log = logging.getLogger(__name__)

EMOJI = {"verde": "🟢", "amarillo": "🟡", "rojo": "🔴"}
COLOR_HEX = {"verde": "2E7D32", "amarillo": "F9A825", "rojo": "C62828"}


# --------------------------------------------------------------------------- #
# Decisión: ¿corresponde notificar?
# --------------------------------------------------------------------------- #

def debe_notificar(
    nivel_actual: str,
    estado_anterior: Optional[Dict[str, Any]],
) -> bool:
    umbral = config.ORDEN_NIVELES.get(config.NIVEL_MINIMO_NOTIFICACION, 1)
    if config.ORDEN_NIVELES.get(nivel_actual, 0) < umbral:
        return False

    if not config.NOTIFICAR_SOLO_CAMBIOS:
        return True

    if not estado_anterior:
        return True

    return estado_anterior.get("nivel_consolidado") != nivel_actual


# --------------------------------------------------------------------------- #
# Composición del mensaje
# --------------------------------------------------------------------------- #

def _texto_plano(estado: Dict[str, Any]) -> str:
    nivel = estado["nivel_consolidado"]
    ts = estado["timestamp_local"]
    lineas = [
        f"{EMOJI.get(nivel, '')} ALERTA DE ANEGAMIENTO — AÑELO",
        f"Nivel del corredor: {nivel.upper()}",
        f"Actualizado: {ts}",
        "",
    ]
    for p in estado["puntos"]:
        lineas.append(
            f"{EMOJI.get(p['nivel'], '')} {p['punto_nombre']}: {p['nivel'].upper()} "
            f"(IIE {p['iie']}) — lluvia ref. {p['precip_referencia_mm']} mm, "
            f"suelo {p['saturacion_suelo_pct']}%"
        )
        for d in p["disparadores"]:
            lineas.append(f"    · {d}")
    lineas += ["", f"Acción: {config.ACCION_POR_NIVEL[nivel]}"]
    return "\n".join(lineas)


def _tarjeta_teams(estado: Dict[str, Any]) -> Dict[str, Any]:
    nivel = estado["nivel_consolidado"]
    return {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "themeColor": COLOR_HEX.get(nivel, "808080"),
        "summary": f"Anegamiento Añelo: {nivel.upper()}",
        "title": f"{EMOJI.get(nivel, '')} Anegamiento de caminos — Añelo: {nivel.upper()}",
        "sections": [
            {
                "activitySubtitle": f"Actualizado {estado['timestamp_local']}",
                "facts": [
                    {
                        "name": p["punto_nombre"],
                        "value": (
                            f"{EMOJI.get(p['nivel'], '')} {p['nivel'].upper()} · "
                            f"IIE {p['iie']} · lluvia {p['precip_referencia_mm']} mm · "
                            f"suelo {p['saturacion_suelo_pct']}%"
                        ),
                    }
                    for p in estado["puntos"]
                ],
                "markdown": True,
            },
            {"text": f"**Acción recomendada:** {config.ACCION_POR_NIVEL[nivel]}"},
        ],
    }


# --------------------------------------------------------------------------- #
# Envío
# --------------------------------------------------------------------------- #

def _post(url: str, payload: Dict[str, Any], destino: str) -> bool:
    try:
        r = get_session().post(url, json=payload, timeout=config.HTTP_TIMEOUT)
        if r.status_code < 300:
            log.info("Notificación enviada a %s", destino)
            return True
        log.error("%s respondió HTTP %s: %s", destino, r.status_code, r.text[:200])
    except requests.RequestException as exc:
        log.error("Error notificando a %s: %s", destino, exc)
    return False


def notificar(estado: Dict[str, Any]) -> List[str]:
    """Envía a todos los canales configurados. Devuelve los canales usados."""
    enviados: List[str] = []

    if config.TEAMS_WEBHOOK_URL:
        if _post(config.TEAMS_WEBHOOK_URL, _tarjeta_teams(estado), "Teams"):
            enviados.append("teams")
    else:
        log.debug("Teams no configurado (falta TEAMS_WEBHOOK_URL).")

    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": _texto_plano(estado),
            "disable_web_page_preview": True,
        }
        if _post(url, payload, "Telegram"):
            enviados.append("telegram")
    else:
        log.debug("Telegram no configurado.")

    if not enviados:
        log.info("Sin canales de notificación configurados. Se omite el envío.")
    return enviados


def previsualizar(estado: Dict[str, Any]) -> str:
    """Para probar el formato del mensaje sin enviarlo (modo --dry-run)."""
    return _texto_plano(estado)
