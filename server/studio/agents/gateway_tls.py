"""Explicit local HTTPS setup for device access and Office task panes."""
from __future__ import annotations
import ipaddress
import secrets
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from .. import config, db
from ..osenv import NO_WINDOW
from . import vault


def paths():
    folder = config.DATA_DIR / 'credentials'
    return folder / 'gateway.crt', folder / 'gateway.key'


def configure():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    certificate, private = paths()
    certificate.parent.mkdir(parents=True, exist_ok=True)
    reference = db.get_setting_values().get('agents.gateway_key_password')
    renew = True
    if certificate.exists() and private.exists() and reference:
        try:
            saved = x509.load_pem_x509_certificate(certificate.read_bytes())
            renew = saved.not_valid_after_utc < datetime.now(timezone.utc) + timedelta(days=30)
        except ValueError:
            renew = True
    if renew:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(timezone.utc)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Grom local device gateway')])
        cert = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()) \
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=365)) \
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'), x509.IPAddress(ipaddress.ip_address('127.0.0.1')), x509.IPAddress(ipaddress.ip_address('::1'))]), critical=False) \
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True).sign(key, hashes.SHA256())
        password = secrets.token_urlsafe(32)
        protected = vault.protect(password)
        private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.BestAvailableEncryption(password.encode())))
        certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        db.set_setting_value('agents.gateway_key_password', protected)
    db.set_setting_value('agents.gateway_tls', True)
    return {'configured': True, 'certificate': str(certificate), 'requires_user_trust': True}


def options():
    if not db.get_setting_values().get('agents.gateway_tls'):
        return {}
    certificate, private = paths()
    reference = db.get_setting_values().get('agents.gateway_key_password')
    if not certificate.exists() or not private.exists() or not reference:
        raise ValueError('Configure the local HTTPS certificate again')
    from cryptography import x509
    cert = x509.load_pem_x509_certificate(certificate.read_bytes())
    if cert.not_valid_after_utc <= datetime.now(timezone.utc): raise ValueError('Local HTTPS certificate expired; renew it in Connections')
    return {'ssl_certfile': str(certificate), 'ssl_keyfile': str(private), 'ssl_keyfile_password': vault.reveal(reference)}


def trust_certificate():
    certificate, _ = paths()
    if not certificate.exists():
        raise ValueError('Configure HTTPS first')
    if sys.platform == 'win32':
        result = subprocess.run(['certutil.exe', '-user', '-addstore', 'Root', str(certificate)], capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
    elif sys.platform == 'darwin':
        from pathlib import Path
        result = subprocess.run(['security', 'add-trusted-cert', '-r', 'trustRoot', '-k', str(Path.home() / 'Library/Keychains/login.keychain-db'), str(certificate)], capture_output=True, text=True, timeout=30)
    else:
        raise ValueError('Import the certificate into your browser trust store; Linux trust-store configuration varies')
    if result.returncode:
        raise ValueError('Certificate trust was not installed. Review your OS certificate settings.')
    return {'trusted_in_user_store': True}
