from unittest.mock import MagicMock, patch

import json

import pytest
from docker.errors import NotFound

from launcher.config import Settings
from launcher.docker_client import (
    ContainerAlreadyExists,
    ContainerNotFound,
    InvalidGatewayId,
    LauncherDockerClient,
    _build_env,
    _devices_kwarg,
)


def settings() -> Settings:
    return Settings(_env_file=None)


def test_build_env_usb_with_device():
    env = _build_env(settings(), "gw-x", "usb", {"device": "/dev/ttyACM0"})
    assert env["GATEWAY_ID"] == "gw-x"
    assert env["GATEWAY_TRANSPORT"] == "usb"
    assert env["MESHTASTIC_USB_DEVICE"] == "/dev/ttyACM0"


def test_build_env_tcp_requires_host():
    with pytest.raises(ValueError):
        _build_env(settings(), "gw-x", "tcp", {})


def test_build_env_tcp_ok():
    env = _build_env(settings(), "gw-x", "tcp", {"host": "10.0.0.5", "port": 4403})
    assert env["GATEWAY_TCP_HOST"] == "10.0.0.5"
    assert env["GATEWAY_TCP_PORT"] == "4403"


def test_build_env_unsupported_transport():
    with pytest.raises(ValueError):
        _build_env(settings(), "gw-x", "http", {})


def test_devices_kwarg_missing_path_raises(tmp_path):
    missing = str(tmp_path / "does-not-exist")
    with pytest.raises(ValueError):
        _devices_kwarg("usb", {"device": missing})


def test_devices_kwarg_existing_path(tmp_path):
    dev = tmp_path / "ttyACM0"
    dev.write_text("")
    assert _devices_kwarg("usb", {"device": str(dev)}) == [f"{dev}:{dev}"]


def test_devices_kwarg_non_usb_is_none():
    assert _devices_kwarg("tcp", {"device": "/dev/ttyACM0"}) is None


def _client_with_fake_docker() -> tuple[LauncherDockerClient, MagicMock]:
    with patch("launcher.docker_client.docker.from_env") as from_env:
        fake_docker = MagicMock()
        from_env.return_value = fake_docker
        client = LauncherDockerClient(settings())
    return client, fake_docker


def test_create_container_rejects_invalid_gateway_id():
    client, _ = _client_with_fake_docker()
    with pytest.raises(InvalidGatewayId):
        client.create_container("gw with spaces", "simulated", {})


def test_create_container_conflicts_with_foreign_container():
    client, fake_docker = _client_with_fake_docker()
    foreign = MagicMock()
    foreign.labels = {}
    fake_docker.containers.get.return_value = foreign
    with pytest.raises(ContainerAlreadyExists):
        client.create_container("gw-x", "simulated", {})


def test_create_container_recreates_own_stale_container():
    client, fake_docker = _client_with_fake_docker()
    own = MagicMock()
    own.labels = {"meshsentinel.gateway": "true"}
    fake_docker.containers.get.return_value = own
    created = MagicMock(id="abc123", status="created")
    fake_docker.containers.run.return_value = created

    result = client.create_container("gw-x", "simulated", {})

    own.remove.assert_called_once_with(force=True)
    fake_docker.containers.run.assert_called_once()
    assert result.gateway_id == "gw-x"
    assert result.container_id == "abc123"


def test_create_container_fresh_name():
    client, fake_docker = _client_with_fake_docker()
    fake_docker.containers.get.side_effect = NotFound("no such container")
    created = MagicMock(id="def456", status="created")
    fake_docker.containers.run.return_value = created

    result = client.create_container("gw-x", "simulated", {})

    assert result.container_id == "def456"
    kwargs = fake_docker.containers.run.call_args.kwargs
    assert kwargs["name"] == "meshsentinel-gateway-gw-x"
    assert kwargs["labels"] == {"meshsentinel.gateway": "true", "meshsentinel.gateway_id": "gw-x"}
    assert kwargs["network"] == "meshsentinel"


def test_create_container_network_mode_excludes_network_and_ports():
    with patch("launcher.docker_client.docker.from_env") as from_env:
        fake_docker = MagicMock()
        from_env.return_value = fake_docker
        client = LauncherDockerClient(
            Settings(_env_file=None, gateway_network_mode="container:meshsentinel-tailscale")
        )
    fake_docker.containers.get.side_effect = NotFound("no such container")
    fake_docker.containers.run.return_value = MagicMock(id="x", status="created")

    client.create_container("gw-x", "tcp", {"host": "100.64.0.1", "vn_enabled": True, "vn_port": 4404})

    kwargs = fake_docker.containers.run.call_args.kwargs
    assert kwargs["network_mode"] == "container:meshsentinel-tailscale"
    assert "network" not in kwargs
    assert kwargs["ports"] is None


def test_create_container_resolves_service_network_mode():
    with patch("launcher.docker_client.docker.from_env") as from_env:
        fake_docker = MagicMock()
        from_env.return_value = fake_docker
        client = LauncherDockerClient(Settings(_env_file=None, gateway_network_mode="service:tailscale"))
    own = MagicMock()
    own.labels = {"com.docker.compose.project": "proj"}
    sidecar = MagicMock(id="side123")
    fake_docker.containers.get.side_effect = [NotFound("no such container"), own]
    fake_docker.containers.list.return_value = [sidecar]
    fake_docker.containers.run.return_value = MagicMock(id="x", status="created")

    client.create_container("gw-x", "simulated", {})

    filters = fake_docker.containers.list.call_args.kwargs["filters"]
    assert "com.docker.compose.service=tailscale" in filters["label"]
    assert "com.docker.compose.project=proj" in filters["label"]
    assert fake_docker.containers.run.call_args.kwargs["network_mode"] == "container:side123"


def test_service_network_mode_without_running_sidecar_fails():
    with patch("launcher.docker_client.docker.from_env") as from_env:
        fake_docker = MagicMock()
        from_env.return_value = fake_docker
        client = LauncherDockerClient(Settings(_env_file=None, gateway_network_mode="service:tailscale"))
    fake_docker.containers.get.side_effect = NotFound("no such container")
    fake_docker.containers.list.return_value = []
    with pytest.raises(RuntimeError):
        client.create_container("gw-x", "simulated", {})


def test_create_container_default_has_no_network_mode():
    client, fake_docker = _client_with_fake_docker()
    fake_docker.containers.get.side_effect = NotFound("no such container")
    fake_docker.containers.run.return_value = MagicMock(id="x", status="created")
    client.create_container("gw-x", "simulated", {})
    assert "network_mode" not in fake_docker.containers.run.call_args.kwargs


def test_destroy_container_not_found():
    client, fake_docker = _client_with_fake_docker()
    fake_docker.containers.get.side_effect = NotFound("no such container")
    with pytest.raises(ContainerNotFound):
        client.destroy_container("gw-x")


def test_destroy_container_refuses_foreign_container():
    client, fake_docker = _client_with_fake_docker()
    foreign = MagicMock()
    foreign.labels = {}
    fake_docker.containers.get.return_value = foreign
    with pytest.raises(ContainerNotFound):
        client.destroy_container("gw-x")


def test_destroy_container_removes_own_container():
    client, fake_docker = _client_with_fake_docker()
    own = MagicMock()
    own.labels = {"meshsentinel.gateway": "true"}
    fake_docker.containers.get.return_value = own
    client.destroy_container("gw-x")
    own.remove.assert_called_once_with(force=True)


def test_build_env_http_requires_host_and_maps_port():
    with pytest.raises(ValueError):
        _build_env(settings(), "gw-x", "http", {})
    env = _build_env(settings(), "gw-x", "http", {"host": "10.0.0.5", "port": 8080})
    assert env["GATEWAY_TRANSPORT"] == "http"
    assert env["GATEWAY_HTTP_HOST"] == "10.0.0.5" and env["GATEWAY_HTTP_PORT"] == "8080"


def test_build_env_mqtt_maps_broker_and_json_fields():
    with pytest.raises(ValueError):
        _build_env(settings(), "gw-x", "mqtt", {})
    env = _build_env(
        settings(), "gw-x", "mqtt",
        {"host": "mqtt.example", "username": "u", "password": "p", "tls": True,
         "channel_keys": {"Mi": "Ag=="}, "geo_bbox": [38.5, -2.5, 39.5, -0.9]},
    )
    assert env["GATEWAY_MQTT_HOST"] == "mqtt.example" and env["GATEWAY_MQTT_TLS"] == "true"
    assert env["GATEWAY_MQTT_USERNAME"] == "u" and env["GATEWAY_MQTT_PASSWORD"] == "p"
    assert json.loads(env["GATEWAY_MQTT_CHANNEL_KEYS"]) == {"Mi": "Ag=="}
    assert json.loads(env["GATEWAY_MQTT_GEO_BBOX"]) == [38.5, -2.5, 39.5, -0.9]


def test_virtual_node_env_and_published_port():
    from launcher.docker_client import _ports_kwarg

    params = {"host": "10.0.0.5", "vn_enabled": True, "vn_port": 4410, "vn_allow_admin": True}
    env = _build_env(settings(), "gw-x", "tcp", params)
    assert env["GATEWAY_VN_ENABLED"] == "true" and env["GATEWAY_VN_PORT"] == "4410"
    assert env["GATEWAY_VN_ALLOW_ADMIN"] == "true"
    assert _ports_kwarg("tcp", params) == {"4410/tcp": 4410}
    # sin activar: ni variables ni puerto publicado; MQTT nunca (no hay nodo)
    off = {"host": "10.0.0.5"}
    assert "GATEWAY_VN_ENABLED" not in _build_env(settings(), "gw-x", "tcp", off)
    assert _ports_kwarg("tcp", off) is None
    assert _ports_kwarg("mqtt", {"host": "b", "vn_enabled": True}) is None


# ── reconcile_network: gateways colgados de un sidecar recreado ──────────────


def _shared_net_client() -> tuple[LauncherDockerClient, MagicMock]:
    with patch("launcher.docker_client.docker.from_env") as from_env:
        fake_docker = MagicMock()
        from_env.return_value = fake_docker
        client = LauncherDockerClient(Settings(_env_file=None, gateway_network_mode="container:sidecar"))
    sidecar = MagicMock()
    sidecar.id = "NEW"
    fake_docker.containers.get.side_effect = lambda ref: sidecar if ref in ("sidecar", "NEW", "OLD") else (_ for _ in ()).throw(NotFound("x"))
    return client, fake_docker


def _gateway_container(network_mode: str, gateway_id: str = "gw-1") -> MagicMock:
    c = MagicMock()
    c.name = f"meshsentinel-gateway-{gateway_id}"
    c.labels = {"meshsentinel.gateway": "true", "meshsentinel.gateway_id": gateway_id}
    c.attrs = {
        "HostConfig": {"NetworkMode": network_mode, "Devices": [
            {"PathOnHost": "/dev/ttyACM0", "PathInContainer": "/dev/ttyACM0", "CgroupPermissions": "rwm"}]},
        "Config": {"Env": ["GATEWAY_ID=gw-1", "GATEWAY_TCP_HOST=10.0.0.5"], "Labels": c.labels},
    }
    return c


def test_reconcile_recreates_gateway_on_stale_network():
    client, fake = _shared_net_client()
    stale = _gateway_container("container:OLD-GONE")
    fake.containers.list.return_value = [stale]
    assert client.reconcile_network() == ["gw-1"]
    stale.remove.assert_called_once_with(force=True)
    kwargs = fake.containers.run.call_args.kwargs
    assert kwargs["network_mode"] == "container:NEW"
    assert kwargs["name"] == "meshsentinel-gateway-gw-1"
    assert kwargs["environment"] == ["GATEWAY_ID=gw-1", "GATEWAY_TCP_HOST=10.0.0.5"]
    assert kwargs["devices"] == ["/dev/ttyACM0:/dev/ttyACM0:rwm"]


def test_reconcile_leaves_up_to_date_gateway_alone():
    client, fake = _shared_net_client()
    ok = _gateway_container("container:NEW")
    fake.containers.list.return_value = [ok]
    assert client.reconcile_network() == []
    ok.remove.assert_not_called()
    fake.containers.run.assert_not_called()


def test_reconcile_noop_without_shared_network_mode():
    client, fake_docker = _client_with_fake_docker()
    assert client.reconcile_network() == []
    fake_docker.containers.list.assert_not_called()


def test_reconcile_waits_when_sidecar_not_running_yet():
    with patch("launcher.docker_client.docker.from_env") as from_env:
        fake = MagicMock()
        from_env.return_value = fake
        client = LauncherDockerClient(Settings(_env_file=None, gateway_network_mode="service:tailscale"))
    fake.containers.list.return_value = []  # ningún sidecar en marcha
    assert client.reconcile_network() == []
    fake.containers.run.assert_not_called()
