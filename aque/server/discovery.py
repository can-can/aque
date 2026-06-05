import socket


def detect_lan_ip() -> str:
    """Best-effort primary LAN IP (no traffic is actually sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def build_service_info(host_ip: str, port: int, name: str = "Aque"):
    from zeroconf import ServiceInfo

    return ServiceInfo(
        "_aque._tcp.local.",
        f"{name}._aque._tcp.local.",
        addresses=[socket.inet_aton(host_ip)],
        port=port,
        properties={},
    )


def register(host_ip: str, port: int):
    """Advertise the server over Bonjour. Returns a Zeroconf handle or None."""
    try:
        from zeroconf import Zeroconf

        zc = Zeroconf()
        zc.register_service(build_service_info(host_ip, port))
        return zc
    except Exception:
        return None
