import socket

from aque.server.discovery import build_service_info, detect_lan_ip


def test_build_service_info_has_type_and_port():
    info = build_service_info("192.168.1.5", 8722)
    assert info.type == "_aque._tcp.local."
    assert info.port == 8722
    assert socket.inet_aton("192.168.1.5") in info.addresses


def test_detect_lan_ip_returns_dotted_quad():
    ip = detect_lan_ip()
    assert isinstance(ip, str)
    assert ip.count(".") == 3
