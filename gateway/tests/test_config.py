from gateway.config import Settings


def test_transport_alias_simulator(monkeypatch):
    monkeypatch.setenv("GATEWAY_TRANSPORT", "simulator")
    assert Settings(_env_file=None).transport == "simulated"


def test_transport_alias_serial_maps_to_usb(monkeypatch):
    monkeypatch.setenv("GATEWAY_TRANSPORT", "serial")
    assert Settings(_env_file=None).transport == "usb"


def test_meshtastic_env_aliases(monkeypatch):
    monkeypatch.setenv("MESHTASTIC_USB_DEVICE", "/dev/ttyACM0")
    monkeypatch.setenv("MESHTASTIC_RECONNECT_INITIAL_DELAY", "2")
    monkeypatch.setenv("MESHTASTIC_RECONNECT_MAX_DELAY", "60")
    s = Settings(_env_file=None)
    assert s.usb_device == "/dev/ttyACM0"
    assert s.reconnect_initial_delay == 2
    assert s.reconnect_max_delay == 60


def test_defaults_autodetect():
    s = Settings(_env_file=None)
    assert s.usb_device == ""
    assert s.reconnect_initial_delay == 5
    assert s.reconnect_max_delay == 300
