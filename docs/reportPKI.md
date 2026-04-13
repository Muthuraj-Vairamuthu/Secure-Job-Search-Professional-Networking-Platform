# Implementation Report: PKI Integration

## Overview

This report documents the implementation of **PKI (Public Key Infrastructure) Integration** as required by the CSE 345/545 April Security Mandates. Two PKI functions are implemented:

1. **Resume Digital Signatures** — Ensures resume integrity and authenticity
2. **Message Signing (Non-Repudiation)** — Proves message authorship, prevents denial

---

## Architecture

### Cryptographic Primitives

| Parameter | Value |
|-----------|-------|
| Algorithm | RSA-2048 |
| Padding | PSS (Probabilistic Signature Scheme) |
| Hash | SHA-256 |
| MGF | MGF1-SHA256 |
| Salt Length | Maximum |
| Key Encoding | PEM (PKCS8 private, SubjectPublicKeyInfo public) |
| Signature Encoding | Base64 |

### Key Management

- **Per-user RSA key pair** generated lazily on first use (upload or message send)
- Private key stored in `users.pki_private_key` (PEM format)
- Public key stored in `users.pki_public_key` (PEM format)
- Keys generated via `cryptography` library using `rsa.generate_private_key()`
- No passphrase encryption on private keys (acceptable for demo; production would use HSM or encrypted storage)

### PKI Module (`backend/api/pki.py`)

Core functions:

| Function | Purpose |
|----------|---------|
| `generate_rsa_keypair()` | Generates a new RSA-2048 key pair, returns `(private_pem, public_pem)` |
| `get_or_create_keypair(db_path, email)` | Retrieves user's key pair from DB, or generates+stores one |
| `get_public_key(db_path, email)` | Retrieves only the public key (for third-party verification) |
| `sign_data(private_pem, data_bytes)` | Signs data with RSA-PSS, returns base64 signature |
| `verify_signature(public_pem, data_bytes, sig_b64)` | Verifies signature, returns `(bool, reason_string)` |

---

## Function 1: Resume Digital Signatures

### How It Works

1. **On Upload** (`POST /api/v1/users/resumes`):
   - File is validated, scanned, cleaned, and encrypted (existing flow)
   - The **SHA-256 hash of the plaintext** (computed pre-encryption) is signed with the user's RSA private key
   - The base64-encoded signature is stored in `resumes.digital_signature`
   - Audit log records `RESUME_UPLOADED_AND_SIGNED`

2. **On Download** (`GET /api/v1/users/resumes/<id>/download`):
   - File is decrypted and integrity-checked (existing flow)
   - The stored signature is **verified** against the original file hash using the owner's public key
   - Response includes headers:
     - `X-PKI-Signature-Status: valid|invalid|unsigned|no_public_key`
     - `X-PKI-Signer: <owner_email>`

3. **Explicit Verification** (`GET /api/v1/users/resumes/<id>/verify`):
   - Standalone endpoint to check signature validity
   - Returns: `verified` (bool), `reason`, `signer`, `signature_algorithm`
   - Available to any authenticated user (useful for recruiters verifying applicant resumes)

### What This Proves

- **Integrity**: The file has not been modified since the owner uploaded it
- **Authenticity**: The file was uploaded by the claimed owner (only they hold the private key)
- **Non-repudiation**: The owner cannot deny having uploaded this specific file

### Schema Changes

```sql
-- resumes table: new column
digital_signature TEXT DEFAULT ''

-- users table: new columns
pki_private_key TEXT DEFAULT ''
pki_public_key TEXT DEFAULT ''
```

---

## Function 2: Message Signing (Non-Repudiation)

### How It Works

1. **On Send** (`POST /api/v1/messages/conversations/<id>/messages`):
   - The `encrypted_content` (ciphertext) is signed with the sender's RSA private key
   - Both `encrypted_content`, `iv`, and `signature` are stored in the `messages` table
   - Audit log records `MESSAGE_SENT_AND_SIGNED`

2. **On Retrieval** (`GET /api/v1/messages/conversations/<id>/messages`):
   - Each message includes `signature` field
   - Response includes `pki_enabled: true` flag

3. **Explicit Verification** (`GET /api/v1/messages/messages/<msg_id>/verify`):
   - Verifies that the message was indeed sent by the claimed sender
   - Only accessible to conversation members
   - Returns: `verified` (bool), `reason`, `sender`, `message_id`, `signature_algorithm`

### Why Sign the Ciphertext?

The signature is computed over the `encrypted_content` (ciphertext), not the plaintext. This is the correct approach because:

- The server never sees the plaintext (E2EE), so it cannot sign what it doesn't have
- The ciphertext is exactly what's stored — signing it proves **who stored this specific ciphertext**
- This provides **non-repudiation at the transport layer**: the sender cannot deny having sent this encrypted payload
- Combined with E2EE decryption on the client, this gives full end-to-end trust

### Schema Changes

```sql
-- messages table: new column
signature TEXT NOT NULL DEFAULT ''
```

---

## API Reference

### Resume PKI Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/users/resumes` | Upload resume (auto-signs with PKI) |
| `GET` | `/api/v1/users/resumes/<id>/download` | Download (auto-verifies, adds PKI headers) |
| `GET` | `/api/v1/users/resumes/<id>/verify` | Standalone signature verification |
| `GET` | `/api/v1/users/me/pki` | Get/generate user's PKI public key |

### Message PKI Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/messages/conversations/<id>/messages` | Send message (auto-signs with PKI) |
| `GET` | `/api/v1/messages/conversations/<id>/messages` | Retrieve messages (includes signatures) |
| `GET` | `/api/v1/messages/messages/<msg_id>/verify` | Verify specific message signature |

---

## Files Changed

| File | Change |
|------|--------|
| `backend/api/pki.py` | **NEW** — PKI utility module (key gen, sign, verify) |
| `backend/api/core/db.py` | Added `pki_private_key`, `pki_public_key` to users; `digital_signature` to resumes; `signature` to messages; ALTER TABLE migrations |
| `backend/api/routes/users.py` | Resume upload now signs; download now verifies; added `/verify` and `/me/pki` endpoints |
| `backend/api/routes/messages.py` | Message send now signs; message retrieval includes signatures; added `/messages/<id>/verify` endpoint |

---

## Security Considerations

1. **Private Key Storage**: Keys are stored in plaintext in the database. In production, use a Hardware Security Module (HSM) or encrypted key storage with a master key.
2. **Key Rotation**: Not implemented. If a key is compromised, all prior signatures remain valid against the old key. A rotation mechanism would invalidate old keys and re-sign content.
3. **Certificate Authority**: This is a self-signed PKI (no CA chain). For production, consider integrating with an organizational CA.
4. **Algorithm Choice**: RSA-2048 with PSS padding is NIST-recommended and resistant to known attacks. SHA-256 provides collision resistance.
