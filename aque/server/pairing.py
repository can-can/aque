import io
import secrets


def generate_token(nbytes: int = 16) -> str:
    """A URL-safe random token."""
    return secrets.token_urlsafe(nbytes)


def pairing_payload(host: str, port: int, token: str) -> dict:
    """The JSON the app scans from the QR code."""
    return {"host": host, "port": port, "token": token}


def render_qr(text: str) -> str:
    """Render ``text`` as an ASCII QR code (for printing to the terminal)."""
    import qrcode

    qr = qrcode.QRCode(border=1)
    qr.add_data(text)
    qr.make(fit=True)
    buf = io.StringIO()
    qr.print_ascii(out=buf)
    return buf.getvalue()
