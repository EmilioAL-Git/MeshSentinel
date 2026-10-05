"""Lectura de config del nodo local desde la caché de la librería (sin admin)."""

from meshtastic.protobuf import localonly_pb2

from gateway.transports.meshtastic_stream import MeshtasticStreamTransport


class _Node:
    def __init__(self) -> None:
        self.localConfig = localonly_pb2.LocalConfig()
        self.moduleConfig = localonly_pb2.LocalModuleConfig()


class _Iface:
    def __init__(self) -> None:
        self.localNode = _Node()

    def getMyUser(self):
        return {"shortName": "T1", "longName": "Test 1"}


def _transport() -> MeshtasticStreamTransport:
    class _T(MeshtasticStreamTransport):
        def _connect_blocking(self): ...
        def _endpoint_description(self): return "test"

    t = _T.__new__(_T)
    t._iface = _Iface()
    return t


def test_local_config_section_from_cache():
    t = _transport()
    t._iface.localNode.localConfig.lora.hop_limit = 5
    out = t._read_local_cache("config.get", {"section": "lora"})
    assert out == {"lora": {"hopLimit": 5}}


def test_missing_section_falls_back_to_admin():
    t = _transport()
    assert t._read_local_cache("module_config.get", {"section": "mqtt"}) is None


def test_owner_from_cache():
    assert _transport()._read_local_cache("nodeinfo.get", {})["shortName"] == "T1"


def test_request_bodies_cover_every_backend_kind():
    from gateway.decoder.requests import build_request
    from meshtastic.protobuf import portnums_pb2 as pn

    iface = _Iface()
    kinds = {
        "user_info": pn.PortNum.NODEINFO_APP, "position": pn.PortNum.POSITION_APP,
        "pax_metrics": pn.PortNum.PAXCOUNTER_APP, "device_metrics": pn.PortNum.TELEMETRY_APP,
        "host_metrics": pn.PortNum.TELEMETRY_APP, "local_stats": pn.PortNum.TELEMETRY_APP,
    }
    for kind, port in kinds.items():
        msg, got = build_request(kind, iface)
        assert got == port and msg is not None
    tel, _ = build_request("power_metrics", iface)
    assert tel.WhichOneof("variant") == "power_metrics"
    user, _ = build_request("user_info", iface)
    assert user.short_name == "T1"
