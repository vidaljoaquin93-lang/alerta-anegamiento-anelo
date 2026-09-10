"""Cliente HTTP con reintentos y backoff exponencial."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import requests

from . import config

log = logging.getLogger(__name__)

_session: Optional[requests.Session] = None


def get_session() -> requests.Session:
    """Sesión única reutilizada (keep-alive) para toda la corrida."""
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({"User-Agent": config.USER_AGENT})
        _session = s
    return _session


def fetch(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = config.HTTP_TIMEOUT,
    reintentos: int = config.HTTP_REINTENTOS,
) -> Optional[requests.Response]:
    """
    GET con reintentos. Devuelve None si agota los reintentos.

    Nunca levanta excepción hacia arriba: la caída temporal de una API no debe
    tumbar la corrida completa de GitHub Actions.
    """
    espera = config.HTTP_BACKOFF
    ultimo_error = ""

    for intento in range(1, reintentos + 1):
        try:
            r = get_session().get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r
            ultimo_error = f"HTTP {r.status_code}"
            # 4xx (salvo 429) no se reintenta: no va a cambiar
            if 400 <= r.status_code < 500 and r.status_code != 429:
                log.warning("GET %s -> %s (no se reintenta)", url, ultimo_error)
                return None
        except requests.RequestException as exc:
            ultimo_error = f"{type(exc).__name__}: {exc}"

        if intento < reintentos:
            log.warning(
                "GET %s falló (%s). Reintento %d/%d en %.1fs",
                url, ultimo_error, intento, reintentos, espera,
            )
            time.sleep(espera)
            espera *= 2

    log.error("GET %s agotó reintentos. Último error: %s", url, ultimo_error)
    return None


def fetch_json(url: str, **kwargs) -> Optional[Any]:
    """GET que devuelve JSON parseado, o None ante cualquier problema."""
    r = fetch(url, **kwargs)
    if r is None:
        return None
    try:
        return r.json()
    except ValueError as exc:
        log.error("Respuesta de %s no es JSON válido: %s", url, exc)
        return None
