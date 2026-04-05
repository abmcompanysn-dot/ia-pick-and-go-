from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import datetime
import ipaddress
import socket

def get_local_ip():
    """Trouve l'adresse IP locale de la machine pour l'inclure dans le certificat."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # n'a pas besoin d'être joignable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

print("Génération de la clé privée...")
key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
    backend=default_backend()
)

with open("key.pem", "wb") as f:
    f.write(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))
print("Fichier 'key.pem' créé.")

local_ip = get_local_ip()
print(f"Utilisation de l'IP locale détectée ({local_ip}) pour le certificat.")

subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, u"abm.edupilote.dev")])

cert_builder = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(
    key.public_key()
).serial_number(x509.random_serial_number()).not_valid_before(
    datetime.datetime.now(datetime.timezone.utc)
).not_valid_after(
    datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)
).add_extension(
    x509.SubjectAlternativeName([x509.DNSName(u"localhost"), x509.IPAddress(ipaddress.ip_address(local_ip))]),
    critical=False,
)

cert = cert_builder.sign(key, hashes.SHA256(), default_backend())

with open("cert.pem", "wb") as f:
    f.write(cert.public_bytes(serialization.Encoding.PEM))

print("✅ Fichier 'cert.pem' créé. Vous pouvez maintenant lancer le serveur en HTTPS.")