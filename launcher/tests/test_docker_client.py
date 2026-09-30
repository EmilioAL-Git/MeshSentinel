from unittest.mock import MagicMock, patch

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
    own.labels = {"noc.gateway": "true"}
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
    assert kwargs["name"] == "noc-gateway-gw-x"
    assert kwargs["labels"] == {"noc.gateway": "true", "noc.gateway_id": "gw-x"}
    assert kwargs["network"] == "meshtastic-noc"


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
    own.labels = {"noc.gateway": "true"}
    fake_docker.containers.get.return_value = own
    client.destroy_container("gw-x")
    own.remove.assert_called_once_with(force=True)
