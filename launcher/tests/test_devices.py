from unittest.mock import patch

from launcher.devices import list_usb_devices


class FakePort:
    def __init__(self, device, description=None, vid=None, pid=None, serial_number=None):
        self.device = device
        self.description = description
        self.vid = vid
        self.pid = pid
        self.serial_number = serial_number


def test_list_usb_devices_maps_fields():
    fake_ports = [
        FakePort("/dev/ttyACM0", description="Meshtastic", vid=0x239A, pid=0x8029, serial_number="ABC123"),
        FakePort("/dev/ttyUSB0", description="n/a"),
    ]
    with patch("launcher.devices.list_ports.comports", return_value=fake_ports):
        devices = list_usb_devices()
    assert devices == [
        {"port": "/dev/ttyACM0", "description": "Meshtastic", "vid": "239A", "pid": "8029", "serial_number": "ABC123"},
        {"port": "/dev/ttyUSB0", "description": None, "vid": None, "pid": None, "serial_number": None},
    ]
