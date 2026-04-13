"""
PKI Module — RSA Digital Signatures for Resume Integrity and Message Non-Repudiation.

Uses RSA-2048 with PSS padding and SHA-256 for signing/verification.
Key pairs are generated per-user on first use and stored in the database.
"""

import base64
import sqlite3
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidSignature


def generate_rsa_keypair():
    """Generate a new RSA-2048 key pair. Returns (private_key_pem, public_key_pem) as strings."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode('utf-8')

    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode('utf-8')

    return private_pem, public_pem


def get_or_create_keypair(db_path, user_email):
    """
    Retrieve the user's RSA key pair from the database.
    If none exists, generate one and store it.
    Returns (private_key_pem, public_key_pem).
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT pki_private_key, pki_public_key FROM users WHERE email=?",
            (user_email,)
        ).fetchone()

        if row and row['pki_private_key'] and row['pki_public_key']:
            return row['pki_private_key'], row['pki_public_key']

        # Generate new key pair
        private_pem, public_pem = generate_rsa_keypair()
        conn.execute(
            "UPDATE users SET pki_private_key=?, pki_public_key=? WHERE email=?",
            (private_pem, public_pem, user_email)
        )
        conn.commit()
        return private_pem, public_pem


def get_public_key(db_path, user_email):
    """Retrieve a user's public key (for verification by others)."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT pki_public_key FROM users WHERE email=?",
            (user_email,)
        ).fetchone()
        if row and row['pki_public_key']:
            return row['pki_public_key']
    return None


def sign_data(private_key_pem, data_bytes):
    """
    Sign arbitrary bytes using the RSA private key with PSS padding.
    Returns the signature as a base64-encoded string.
    """
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode('utf-8'),
        password=None,
        backend=default_backend()
    )
    signature = private_key.sign(
        data_bytes,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode('utf-8')


def verify_signature(public_key_pem, data_bytes, signature_b64):
    """
    Verify a signature against the data using the RSA public key.
    Returns (True, "Valid") or (False, "reason").
    """
    try:
        public_key = serialization.load_pem_public_key(
            public_key_pem.encode('utf-8'),
            backend=default_backend()
        )
        signature = base64.b64decode(signature_b64)
        public_key.verify(
            signature,
            data_bytes,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        return True, "Signature is valid"
    except InvalidSignature:
        return False, "Signature verification failed — data may have been tampered with"
    except Exception as e:
        return False, f"Verification error: {str(e)}"
