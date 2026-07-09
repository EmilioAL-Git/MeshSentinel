"""Transporte simulado (ADR 0007): malla ficticia determinista por seed."""

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Any

from gateway.config import Settings
from gateway.transports.base import EmitFn, Transport

logger = logging.getLogger("gateway.sim")

HW_MODELS = ["TBEAM", "HELTEC_V3", "RAK4631", "T_ECHO", "STATION_G2"]
ROLES = ["CLIENT", "CLIENT", "CLIENT", "ROUTER", "REPEATER"]


@dataclass
class SimNode:
    node_id: str
    node_num: int
    short_name: str
    long_name: str
    hw_model: str
    role: str
    lat: float
    lon: float
    battery: float = 100.0
    has_gps: bool = True
    fixed_position: bool = False
    uptime: int = 0
    # Estado editable por SETs genéricos (M1.4). Se aplica sobre los defaults
    # cannedados en config.get / module_config.get para que el read-back refleje
    # los cambios pedidos.
    config_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    module_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    rng: random.Random = field(default_factory=random.Random)
    # Favoritos/ignorados/contactos remotos (M4.1): NodeDB simulada de ESTE
    # nodo (claves = node_num de otros nodos), fiel a que el firmware no
    # expone forma de leerlos de vuelta (ADR 0019).
    favorites: set[int] = field(default_factory=set)
    ignored_nodes: set[int] = field(default_factory=set)
    known_contacts: set[int] = field(default_factory=set)


class SimulatedTransport(Transport):
    name = "simulated"

    def __init__(self, emit: EmitFn, settings: Settings) -> None:
        super().__init__(emit)
        self._settings = settings
        self._rng = random.Random(settings.sim_seed)
        self._nodes = self._build_mesh(settings.sim_node_count)
        self._closed = asyncio.Event()

    def _build_mesh(self, count: int) -> list[SimNode]:
        nodes = []
        for i in range(count):
            num = self._rng.randrange(0x10000000, 0xFFFFFFFF)
            nodes.append(
                SimNode(
                    node_id=f"!{num:08x}",
                    node_num=num,
                    short_name=f"SIM{i:02d}",
                    long_name=f"Nodo simulado {i:02d}",
                    hw_model=self._rng.choice(HW_MODELS),
                    role=self._rng.choice(ROLES),
                    lat=self._settings.sim_center_lat + self._rng.uniform(-0.05, 0.05),
                    lon=self._settings.sim_center_lon + self._rng.uniform(-0.05, 0.05),
                    battery=self._rng.uniform(40, 100),
                    has_gps=self._rng.random() > 0.25,
                    rng=random.Random(self._rng.random()),
                )
            )
        return nodes

    async def run(self) -> None:
        self.status = "connected"
        local = self._nodes[0]
        self.local_node_id = local.node_id
        self.local_short_name = local.short_name
        self.local_long_name = local.long_name
        self.local_hw_model = local.hw_model
        self.local_firmware_version = "2.7.0"
        await self.emit_status()
        for node in self._nodes:
            await self._announce(node)

        interval = self._settings.sim_telemetry_interval_seconds
        while not self._closed.is_set():
            await asyncio.sleep(interval)
            for node in self._nodes:
                await self._tick(node, interval)

    async def _announce(self, node: SimNode) -> None:
        await self._emit(
            "node.seen",
            {
                "node_id": node.node_id,
                "node_num": node.node_num,
                "short_name": node.short_name,
                "long_name": node.long_name,
                "hw_model": node.hw_model,
                "firmware_version": "2.7.0",
                "role": node.role,
                "snr": round(node.rng.uniform(-12, 10), 2),
                "rssi": node.rng.randint(-130, -60),
                "hops_away": node.rng.randint(0, 3),
                "via_mqtt": False,
                "public_key": None,
            },
        )

    async def _tick(self, node: SimNode, elapsed: int) -> None:
        node.uptime += elapsed
        node.battery = max(5.0, node.battery - node.rng.uniform(0, 0.05))

        # No todos los nodos transmiten en cada intervalo: la malla es esporádica
        if node.rng.random() < 0.4:
            await self._emit(
                "telemetry.received",
                {
                    "node_id": node.node_id,
                    "kind": "device",
                    "battery_level": int(node.battery),
                    "voltage": round(3.3 + node.battery / 100, 2),
                    "channel_utilization": round(node.rng.uniform(0, 25), 1),
                    "air_util_tx": round(node.rng.uniform(0, 8), 1),
                    "uptime_seconds": node.uptime,
                },
            )
        if node.has_gps and node.rng.random() < 0.2:
            node.lat += node.rng.uniform(-0.0005, 0.0005)
            node.lon += node.rng.uniform(-0.0005, 0.0005)
            await self._emit(
                "position.updated",
                {
                    "node_id": node.node_id,
                    "latitude": round(node.lat, 6),
                    "longitude": round(node.lon, 6),
                    "altitude_m": node.rng.randint(600, 700),
                    "precision_bits": 32,
                    "sats_in_view": node.rng.randint(4, 12),
                },
            )

    async def send_command(self, command: dict[str, Any]) -> None:
        logger.info("Simulated execution of %s -> %s", command.get("command_type"), command.get("target_node_id"))

    # ── Administración simulada (M1.1): permite validar el pipeline completo
    # sin hardware, con latencias y timeouts deterministas por seed (ADR 0007).

    async def execute_admin(self, operation: dict[str, Any]) -> dict[str, Any]:
        node_id = str(operation["target_node_id"]).lower()
        node = next((n for n in self._nodes if n.node_id == node_id), None)
        if node is None:
            await asyncio.sleep(2)
            raise TimeoutError(f"node {node_id} not in simulated mesh")

        await asyncio.sleep(node.rng.uniform(0.5, 2.0))  # latencia LoRa simulada
        if node.rng.random() < 0.10:  # ~10% de peticiones se pierden: ejercita reintentos
            raise TimeoutError("simulated packet loss")

        op_type = operation["operation_type"]
        params = operation.get("params") or {}
        if op_type == "metadata.get":
            return {
                "firmwareVersion": "2.7.0",
                "deviceStateVersion": 24,
                "hwModel": node.hw_model,
                "hasWifi": False,
                "hasBluetooth": True,
                "role": node.role,
            }
        if op_type == "nodeinfo.get":
            return {
                "id": node.node_id,
                "longName": node.long_name,
                "shortName": node.short_name,
                "hwModel": node.hw_model,
                "isLicensed": False,
            }
        if op_type == "config.get":
            section = params.get("section", "device")
            defaults: dict[str, dict[str, Any]] = {
                "lora": {"region": "EU_868", "hopLimit": 3, "txEnabled": True, "sx126xRxBoostedGain": True},
                "device": {"role": node.role, "nodeInfoBroadcastSecs": 10800},
                "position": {"positionBroadcastSecs": 900, "gpsMode": "ENABLED" if node.has_gps else "NOT_PRESENT"},
                "display": {"screenOnSecs": 60, "gpsFormat": "DEC"},
                "power": {"waitBluetoothSecs": 60, "sdsSecs": 4294967295},
                "bluetooth": {"enabled": True, "mode": "RANDOM_PIN"},
                "network": {"wifiEnabled": False, "ntpServer": "0.pool.ntp.org"},
                "security": {"isManaged": False, "serialEnabled": True},
                "device_ui": {"screenBrightness": 128},
            }
            base = defaults.get(section, {"enabled": True})
            override = node.config_state.get(section, {})
            return {section: {**base, **override}}
        if op_type == "module_config.get":
            section = params.get("section", "telemetry")
            base = {"enabled": section == "telemetry"}
            override = node.module_state.get(section, {})
            return {section: {**base, **override}}

        # SETs verificables (M1.3): se aplican a la malla simulada y el verify
        # se confirma con el mismo read-back que usaría el transporte real
        if op_type == "owner.set":
            previous = {"id": node.node_id, "longName": node.long_name, "shortName": node.short_name}
            if params.get("short_name") is not None:
                node.short_name = params["short_name"]
            if params.get("long_name") is not None:
                node.long_name = params["long_name"]
            await asyncio.sleep(node.rng.uniform(0.5, 2.0))
            verified = {"id": node.node_id, "longName": node.long_name, "shortName": node.short_name}
            confirmed = all(
                verified[key] == value
                for key, value in (
                    ("shortName", params.get("short_name")),
                    ("longName", params.get("long_name")),
                )
                if value is not None
            )
            await self._announce(node)  # el nodo difunde su nueva identidad
            return {
                "previous": previous,
                "requested": params,
                "verified": verified,
                "verify": "confirmed" if confirmed else "mismatch",
            }
        if op_type == "position.set_fixed":
            previous = {"position": {"fixedPosition": node.fixed_position}}
            node.lat, node.lon = params["latitude"], params["longitude"]
            node.has_gps = True
            node.fixed_position = True
            await asyncio.sleep(node.rng.uniform(0.5, 2.0))
            return {
                "previous": previous,
                "requested": params,
                "verified": {"position": {"fixedPosition": True}},
                "verify": "confirmed",
            }

        # SETs genéricos del editor de configuración (M1.4): guardan el diff en
        # el estado local del nodo y responden a los GETs siguientes con los
        # valores actualizados, para que el verify read-back del pipeline pase.
        if op_type in ("config.set", "module_config.set"):
            section = params["section"]
            values = params["values"]
            store = node.config_state if op_type == "config.set" else node.module_state
            previous_section = dict(store.get(section, {}))
            new_section = {**previous_section, **values}
            store[section] = new_section
            await asyncio.sleep(node.rng.uniform(0.5, 2.0))
            return {
                "previous": {section: previous_section},
                "requested": params,
                "verified": {section: new_section},
                "verify": "confirmed",
            }
        # Favoritos/ignorados/ficha de contacto (M4.1, ADR 0019): sin lectura
        # de verificación posible (fiel al firmware real), solo ACK.
        if op_type in ("favorite.set", "favorite.remove", "ignored.set", "ignored.remove", "contact.add"):
            subject_num = int(params["subject_node_id"][1:], 16)
            await asyncio.sleep(node.rng.uniform(0.3, 1.0))
            if op_type == "favorite.set":
                node.favorites.add(subject_num)
            elif op_type == "favorite.remove":
                node.favorites.discard(subject_num)
            elif op_type == "ignored.set":
                node.ignored_nodes.add(subject_num)
            elif op_type == "ignored.remove":
                node.ignored_nodes.discard(subject_num)
            else:
                node.known_contacts.add(subject_num)
            return {
                "requested": params,
                "ack": {"ack": True, "error_reason": "NONE"},
                "verify": "unavailable",
            }

        raise ValueError(f"Unsupported admin operation: {op_type}")

    async def close(self) -> None:
        self._closed.set()
        self.status = "disconnected"
        await self.emit_status(detail="shutdown")
