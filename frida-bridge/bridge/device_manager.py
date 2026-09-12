"""One shared frida.DeviceManager for the whole process. Remote devices
added via add_remote_device() only live in the DeviceManager instance they
were added to — a fresh manager forgets them — so the device-picker HTTP
server (device_server.py) and the actual trace runner (runner.py) both need
to share this exact instance, not create their own."""

import frida

# Frida always reports these three regardless of what's actually plugged
# in/added — they're not real user-selectable devices.
BUILTIN_DEVICE_IDS = {"local", "socket", "barebone"}

_manager: "frida.core.DeviceManager | None" = None


def get_manager() -> "frida.core.DeviceManager":
    global _manager
    if _manager is None:
        _manager = frida.get_device_manager()
    return _manager


def list_devices() -> list[dict]:
    return [
        {"id": d.id, "name": d.name, "type": d.type}
        for d in get_manager().enumerate_devices()
        if d.id not in BUILTIN_DEVICE_IDS
    ]


def add_remote_device(address: str) -> dict:
    dev = get_manager().add_remote_device(address)
    return {"id": dev.id, "name": dev.name, "type": dev.type}


def remove_remote_device(address: str) -> None:
    get_manager().remove_remote_device(address)


def get_device(device_id: str | None, usb_timeout: int):
    """Resolve the device to use for a trace: a specific one by id if the
    caller picked one, otherwise fall back to the default USB device."""
    if device_id:
        return get_manager().get_device_by_id(device_id, timeout=usb_timeout)
    return get_manager().get_usb_device(timeout=usb_timeout)
