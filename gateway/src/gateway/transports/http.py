"""Transporte HTTP de nodo Meshtastic (ADR 0032): API HTTP del firmware (WiFi,
`/api/v1/fromradio` y `/api/v1/toradio`) en lugar del TCP del puerto 4403.

La librería oficial ya no incluye una `HTTPInterface`, así que se implementa
aquí sobre `MeshInterface` (la misma base que usan Serial/TCP): solo cambian
CÓMO se envían y reciben las tramas; todo el comportamiento (reconexión,
snapshot, telemetría, pipeline admin) es el heredado de
`MeshtasticStreamTransport` (ADR 0023: sin forks por transporte).

Ventaja operativa frente a TCP: el servidor HTTP del firmware no está limitado
a un único cliente, así que la app oficial y la pasarela pueden coexistir.
"""

import logging
import threading
from typing import Any, Callable

import requests
from meshtastic.mesh_interface import MeshInterface

from gateway.config import Settings
from gateway.transports.base import EmitFn
from gateway.transports.meshtastic_stream import MeshtasticStreamTransport

logger = logging.getLogger("gateway.transport")

# Sondeo de FromRadio: el firmware devuelve UNA trama por GET (vacío = no hay).
_POLL_IDLE_SECONDS = 0.25
_MAX_CONSECUTIVE_ERRORS = 5
# El volcado inicial va una trama por GET (~0,15 s cada una): con 200 nodos
# tarda ~40 s (medido en un nodo real). `all=true` devuelve las tramas
# concatenadas sin delimitador, no se pueden separar de forma fiable.
_CONFIG_SYNC_TIMEOUT_SECONDS = 150.0


class HttpMeshInterface(MeshInterface):
    def __init__(
        self,
        hostname: str,
        port: int = 80,
        timeout: int = 20,
        on_created: Callable[["HttpMeshInterface"], None] | None = None,
    ) -> None:
        self.url = f"http://{hostname}:{port}"
        self._http_timeout = timeout
        self._session = requests.Session()
        self._wantExit = False
        self._rxThread = threading.Thread(target=self._reader, daemon=True, name="http reader")
        MeshInterface.__init__(self, timeout=timeout)
        if on_created is not None:
            on_created(self)  # el transporte puede abortarla mientras conecta
        try:
            self.connect()
        except Exception:
            self.close()
            raise

    def connect(self) -> None:
        # Falla rápido si el nodo no responde antes de lanzar el lector
        self._session.get(f"{self.url}/api/v1/fromradio?all=false", timeout=self._http_timeout)
        self._rxThread.start()
        self._startConfig()
        self._waitConnected(timeout=_CONFIG_SYNC_TIMEOUT_SECONDS)
        if self._wantExit:
            raise ConnectionError("conexión HTTP abortada")

    def _sendToRadioImpl(self, toRadio: Any) -> None:
        resp = self._session.put(
            f"{self.url}/api/v1/toradio",
            data=toRadio.SerializeToString(),
            headers={"Content-Type": "application/x-protobuf"},
            timeout=self._http_timeout,
        )
        resp.raise_for_status()

    def _reader(self) -> None:
        errors = 0
        while not self._wantExit:
            try:
                resp = self._session.get(
                    f"{self.url}/api/v1/fromradio?all=false", timeout=self._http_timeout
                )
                resp.raise_for_status()
                errors = 0
                if resp.content:
                    self._handleFromRadio(resp.content)
                    continue  # puede haber más tramas pendientes: sin pausa
            except Exception as exc:
                if self._wantExit:
                    break
                errors += 1
                logger.warning("http.read_error n=%d error=%r", errors, exc)
                if errors >= _MAX_CONSECUTIVE_ERRORS:
                    self._disconnected()  # connection.lost → reconexión del transporte
                    break
            threading.Event().wait(_POLL_IDLE_SECONDS)

    def close(self) -> None:
        self._wantExit = True
        self.isConnected.set()  # despierta un _waitConnected en curso
        try:
            MeshInterface.close(self)  # envía ToRadio.disconnect (best effort)
        except Exception:
            logger.debug("http.close_send_failed", exc_info=True)
        if self._rxThread.is_alive() and self._rxThread is not threading.current_thread():
            self._rxThread.join(timeout=self._http_timeout + 1)
        self._session.close()


class MeshtasticHttpTransport(MeshtasticStreamTransport):
    name = "http"

    def __init__(self, emit: EmitFn, settings: Settings) -> None:
        if not settings.http_host:
            raise ValueError("HTTP transport requires a host (GATEWAY_HTTP_HOST / connection_params.host)")
        super().__init__(emit, settings)
        self._tracked: set[HttpMeshInterface] = set()

    def _connect_blocking(self) -> Any:
        return HttpMeshInterface(
            self._settings.http_host,
            self._settings.http_port,
            timeout=int(self._settings.connect_timeout),
            on_created=self._tracked.add,
        )

    def _abort_pending_connect(self) -> None:
        # Una interfaz aún sincronizando no se puede cancelar desde asyncio:
        # se cierra aquí para que su hilo lector deje de robar tramas al nodo.
        for iface in list(self._tracked):
            try:
                iface.close()
            except Exception:
                logger.debug("http.abort_close_error", exc_info=True)
        self._tracked.clear()

    def _endpoint_description(self) -> str:
        return f"{self._settings.http_host}:{self._settings.http_port}"
