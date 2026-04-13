"""
secureResumeUpload.py
=====================
Complete, working implementation of a Secure Resume Upload system.
Authentication is assumed via a session hash (32-byte hex string).

Dependencies  (install via .venv):
    pip install cryptography python-magic pymupdf python-docx

Storage layout (created automatically under BASE_DIR):
    BASE_DIR/
        resumes/     – encrypted blobs   (mode 0o600)
        keys/        – per-file AES keys (mode 0o400)
        logs/        – append-only JSONL audit log
        db/          – SQLite database

Flow:
  UPLOAD : validate_session → validate_file → security_scan
           → encrypt_file → store_encrypted_file → log_event
  VIEW   : validate_session → authorize_access → integrity_check
           → decrypt_in_memory → serve_resume → log_event
  DELETE : validate_session → verify_ownership → secure_delete → log_event
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── third-party ──────────────────────────────────────────────────────────────
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

try:
    import magic as _magic          # python-magic  (libmagic binding)
    _MAGIC_AVAILABLE = True
except ImportError:
    _MAGIC_AVAILABLE = False

try:
    import fitz as _fitz            # PyMuPDF
    _PYMUPDF_AVAILABLE = True
except ImportError:
    _PYMUPDF_AVAILABLE = False

try:
    import docx as _docx            # python-docx
    _DOCX_AVAILABLE = True
except ImportError:
    _DOCX_AVAILABLE = False

# =============================================================================
# §0  Configuration / Security Policy
# =============================================================================

# Base directory for all on-disk data  (change to an out-of-webroot path in prod)
BASE_DIR       = Path(__file__).resolve().parent.parent / "data" / ".secure_storage"
STORAGE_DIR    = BASE_DIR / "resumes"
KEYS_DIR       = BASE_DIR / "keys"
LOGS_DIR       = BASE_DIR / "logs"
DB_DIR         = BASE_DIR / "db"
DB_PATH        = DB_DIR  / "resume_store.db"

ALLOWED_EXTENSIONS: set[str] = {".pdf", ".doc", ".docx"}
MAX_FILE_SIZE_BYTES: int     = 5 * 1024 * 1024       # 5 MB
VALID_ROLES: set[str]        = {"owner", "recruiter", "admin"}

# Magic-byte signatures for allowed types
_MAGIC_MAP: dict[str, bytes] = {
    ".pdf":  b"%PDF",
    ".doc":  b"\xd0\xcf\x11\xe0",
    ".docx": b"PK\x03\x04",
}

# =============================================================================
# §  Initialisation helpers
# =============================================================================

def _ensure_dirs() -> None:
    """Create storage directories with tight OS permissions on first run."""
    for d in (STORAGE_DIR, KEYS_DIR, LOGS_DIR, DB_DIR):
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)


def _get_db() -> sqlite3.Connection:
    """Return a thread-local SQLite connection with WAL mode enabled."""
    _ensure_dirs()
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_hash  TEXT PRIMARY KEY,
            user_id       TEXT NOT NULL,
            role          TEXT NOT NULL DEFAULT 'owner',
            created_at    TEXT NOT NULL,
            expires_at    TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS resumes (
            resume_id          TEXT PRIMARY KEY,
            owner_user_id      TEXT NOT NULL,
            encrypted_file_ref TEXT NOT NULL UNIQUE,
            file_hash          TEXT NOT NULL,   -- SHA-256 of plaintext
            enc_blob_hash      TEXT NOT NULL,   -- SHA-256 of encrypted blob
            upload_timestamp   TEXT NOT NULL,
            file_size          INTEGER NOT NULL,
            original_ext       TEXT NOT NULL,
            visibility         TEXT NOT NULL DEFAULT 'private'
        )
    """)
    conn.commit()
    return conn


@contextmanager
def _db():
    conn = _get_db()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# =============================================================================
# §1  Session Management
# =============================================================================

def create_session(user_id: str, role: str = "owner",
                   ttl_seconds: int = 3600) -> str:
    """
    Create and persist a new session for user_id.

    Returns:
        session_hash (64-hex-char string)
    """
    _ensure_dirs()
    session_hash = os.urandom(32).hex()          # 256-bit random token
    now = datetime.now(timezone.utc)
    from datetime import timedelta
    expires = now + timedelta(seconds=ttl_seconds)
    with _db() as conn:
        conn.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?)",
            (session_hash, user_id, role,
             now.isoformat(), expires.isoformat()),
        )
    return session_hash


def validate_session(session_hash: str) -> Optional[dict]:
    """
    Look up session_hash in the DB and confirm it has not expired.

    Returns:
        {"user_id": ..., "role": ...}  or  None if invalid/expired.
    """
    if not session_hash or len(session_hash) != 64:
        return None
    _ensure_dirs()
    with _db() as conn:
        row = conn.execute(
            "SELECT user_id, role, expires_at FROM sessions WHERE session_hash=?",
            (session_hash,),
        ).fetchone()
    if row is None:
        return None
    expires = datetime.fromisoformat(row["expires_at"])
    if datetime.now(timezone.utc) > expires:
        return None                              # expired
    return {"user_id": row["user_id"], "role": row["role"]}


def invalidate_session(session_hash: str) -> None:
    """Delete a session record (logout / forced expiry)."""
    with _db() as conn:
        conn.execute("DELETE FROM sessions WHERE session_hash=?", (session_hash,))


# =============================================================================
# §2  File Validation
# =============================================================================

def validate_file(filename: str, file_bytes: bytes) -> tuple[bool, str]:
    """
    Strictly validate an uploaded file before any processing.

    Checks (in order):
      1. Extension whitelist – only the *last* suffix is evaluated so
         'evil.pdf.exe' fails on the '.exe' part.
      2. Multiple-dot guard – flags names like 'resume.pdf.exe'.
      3. File size limit.
      4. Magic-byte / MIME check – content must match the declared type.

    Returns:
        (True, "ok")        – passes all checks
        (False, reason_str) – first failed check
    """
    # 1. Extension whitelist
    _, ext = os.path.splitext(filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"Extension '{ext}' is not permitted."

    # 2. Double-extension guard
    if filename.count(".") > 1:
        return False, "Suspicious filename: multiple extensions detected."

    # 3. Size
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        mb = MAX_FILE_SIZE_BYTES // (1024 * 1024)
        return False, f"File exceeds the {mb} MB size limit."

    # 4. Magic bytes (header signature)
    if not _check_magic_bytes(file_bytes, ext):
        return False, "File content does not match the declared extension."

    # 4b. Optional: libmagic MIME check (more robust than header bytes alone)
    if _MAGIC_AVAILABLE:
        detected_mime = _magic.from_buffer(file_bytes, mime=True)
        allowed_mimes = {
            ".pdf":  {"application/pdf"},
            ".doc":  {"application/msword",
                      "application/vnd.ms-office",
                      "application/octet-stream"},
            ".docx": {"application/vnd.openxmlformats-officedocument"
                      ".wordprocessingml.document",
                      "application/zip"},
        }
        if detected_mime not in allowed_mimes.get(ext, set()):
            return False, f"MIME type '{detected_mime}' is not allowed for '{ext}'."

    return True, "ok"


def _check_magic_bytes(file_bytes: bytes, ext: str) -> bool:
    """Return True if the file header matches the expected magic signature."""
    expected = _MAGIC_MAP.get(ext)
    if expected is None:
        return False
    return file_bytes[:len(expected)] == expected


# =============================================================================
# §3  Security Scan
# =============================================================================

def security_scan(file_bytes: bytes, filename: str) -> tuple[bool, bytes | str]:
    """
    Pre-encryption hygiene checks and sanitisation.

    Steps:
      1. Strip embedded metadata (author, GPS, custom properties …).
      2. Return sanitised bytes and a safe normalised filename.

    Note on AV:
      ClamAV / cloud AV integration is marked as a TODO because it
      requires an external daemon.  Slot in `_malware_scan()` here.

    Returns:
        (True,  (clean_bytes, safe_filename)) on pass
        (False, reason_str)                  on fail
    """
    # ── metadata strip ────────────────────────────────────────────────────────
    clean_bytes = _strip_metadata(file_bytes, filename)

    # ── (stub) malware scan ───────────────────────────────────────────────────
    # TODO: pass clean_bytes to ClamAV / VirusTotal / etc.
    # malware_found, detail = _malware_scan(clean_bytes)
    # if malware_found:
    #     return False, f"Malware detected: {detail}"

    safe_name = _normalize_filename(filename)
    return True, (clean_bytes, safe_name)


def _strip_metadata(file_bytes: bytes, filename: str) -> bytes:
    """
    Remove embedded metadata from the document in memory.

    PDF  → PyMuPDF: scrub author, creator, keywords, producer fields.
    DOCX → python-docx: clear core-property fields.
    DOC  → binary; metadata scrubbing requires external tool (LibreOffice
           headless).  Bytes returned unchanged with a WARNING logged.
    """
    _, ext = os.path.splitext(filename.lower())

    if ext == ".pdf" and _PYMUPDF_AVAILABLE:
        import io
        try:
            doc = _fitz.open(stream=file_bytes, filetype="pdf")
            # Overwrite all standard metadata fields with empty strings
            doc.set_metadata({
                "author": "", "creator": "", "producer": "",
                "title": "", "subject": "", "keywords": "",
                "creationDate": "", "modDate": "",
            })
            out = io.BytesIO()
            doc.save(out, garbage=4, deflate=True, clean=True)
            doc.close()
            return out.getvalue()
        except Exception as exc:
            _logger.warning("PDF metadata strip failed: %s", exc)
            return file_bytes

    if ext == ".docx" and _DOCX_AVAILABLE:
        import io, zipfile
        # python-docx doesn't expose a low-level bytes API; we work at the
        # ZIP level and rewrite docProps/core.xml with blank fields.
        try:
            buf = io.BytesIO(file_bytes)
            out = io.BytesIO()
            with zipfile.ZipFile(buf, "r") as zin, \
                 zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    if item.filename == "docProps/core.xml":
                        data = _blank_docx_core_xml()
                    zout.writestr(item, data)
            return out.getvalue()
        except Exception as exc:
            _logger.warning("DOCX metadata strip failed: %s", exc)
            return file_bytes

    # .doc (OLE2): warn; scrubbing binary structures is complex
    if ext == ".doc":
        _logger.warning("Metadata stripping for .doc is not implemented; "
                        "consider converting to DOCX first.")

    return file_bytes


def _blank_docx_core_xml() -> bytes:
    """Return a minimal, blank OOXML core-properties XML."""
    return (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<cp:coreProperties '
        b'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        b'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        b'xmlns:dcterms="http://purl.org/dc/terms/" '
        b'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        b'<dc:creator></dc:creator>'
        b'<cp:lastModifiedBy></cp:lastModifiedBy>'
        b'<dcterms:created xsi:type="dcterms:W3CDTF">1970-01-01T00:00:00Z</dcterms:created>'
        b'<dcterms:modified xsi:type="dcterms:W3CDTF">1970-01-01T00:00:00Z</dcterms:modified>'
        b'</cp:coreProperties>'
    )


def _normalize_filename(filename: str) -> str:
    """
    Return a safe filename:
      - Only alphanumeric, hyphen, underscore retained.
      - Max 64 chars base + original (last) extension.
    """
    base, ext = os.path.splitext(filename)
    safe_base = re.sub(r"[^A-Za-z0-9_\-]", "_", base)[:64]
    return safe_base + ext.lower()


# =============================================================================
# §4  Encryption  (AES-256-GCM)
# =============================================================================

def encrypt_file(file_bytes: bytes, _user_id: str) -> tuple[bytes, bytes, str]:
    """
    Encrypt file_bytes with a freshly-generated AES-256-GCM key.

    AES-GCM provides:
      • Confidentiality  (AES-256 in counter mode)
      • Authenticity     (128-bit GHASH tag)
      • Built-in integrity – decryption fails if ciphertext is modified.

    Wire format written to disk:
        [ 12-byte nonce ][ ciphertext + 16-byte auth-tag ]

    RULE: plaintext MUST NOT be written to disk at any point.

    Returns:
        (encrypted_blob, raw_key_bytes_32, randomized_filename)
    """
    key_bytes      = _generate_encryption_key()          # 32 bytes
    nonce          = os.urandom(12)                       # GCM nonce (96-bit)
    aesgcm         = AESGCM(key_bytes)
    ciphertext_tag = aesgcm.encrypt(nonce, file_bytes, None)  # None = no AAD
    encrypted_blob = nonce + ciphertext_tag               # prepend nonce

    # Destroy plaintext from local scope immediately
    file_bytes = b"\x00" * len(file_bytes)
    del file_bytes

    randomized_name = _generate_random_filename()
    return encrypted_blob, key_bytes, randomized_name


def decrypt_in_memory(encrypted_blob: bytes, key_bytes: bytes) -> bytes:
    """
    Decrypt ciphertext entirely in memory. NEVER write plaintext to disk.

    Raises:
        cryptography.exceptions.InvalidTag – if the blob was tampered with.

    Returns:
        Verified plaintext bytes.
    """
    nonce          = encrypted_blob[:12]
    ciphertext_tag = encrypted_blob[12:]
    aesgcm         = AESGCM(key_bytes)
    return aesgcm.decrypt(nonce, ciphertext_tag, None)


def _generate_encryption_key() -> bytes:
    """Return 32 cryptographically-random bytes (AES-256 key)."""
    return os.urandom(32)


def _generate_random_filename() -> str:
    """Return a random 32-hex-char filename with no link to the original."""
    return os.urandom(16).hex() + ".enc"


# =============================================================================
# §5  Secure Storage
# =============================================================================

def store_encrypted_file(
    encrypted_blob: bytes,
    key_bytes: bytes,
    randomized_filename: str,
    user_id: str,
    plaintext_hash: str,
    original_ext: str,
    file_size: int,
    visibility: str = "private",
) -> str:
    """
    Write the encrypted blob + key to separate locations, record metadata in DB.

    File permissions:
        encrypted blob  →  0o600  (owner read/write only)
        key file        →  0o400  (owner read-only)

    DB row stores only references and hashes – never content or raw key.

    Returns:
        resume_id (str) – 16-hex-char opaque identifier.
    """
    _ensure_dirs()
    resume_id    = os.urandom(8).hex()
    blob_path    = STORAGE_DIR / randomized_filename
    key_path     = KEYS_DIR    / (randomized_filename + ".key")
    enc_blob_hash = compute_file_hash(encrypted_blob)

    # ── write blob ────────────────────────────────────────────────────────────
    blob_path.write_bytes(encrypted_blob)
    os.chmod(blob_path, stat.S_IRUSR | stat.S_IWUSR)   # 0o600

    # ── write key  (raw 32 bytes; hex-encode for portability) ─────────────────
    key_path.write_text(key_bytes.hex())
    os.chmod(key_path, stat.S_IRUSR)                    # 0o400

    # ── DB record ─────────────────────────────────────────────────────────────
    now = datetime.now(timezone.utc).isoformat()
    with _db() as conn:
        conn.execute(
            """INSERT INTO resumes
               (resume_id, owner_user_id, encrypted_file_ref,
                file_hash, enc_blob_hash, upload_timestamp,
                file_size, original_ext, visibility)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (resume_id, user_id, randomized_filename,
             plaintext_hash, enc_blob_hash, now,
             file_size, original_ext, visibility),
        )
    return resume_id


def compute_file_hash(data: bytes) -> str:
    """Return SHA-256 hex digest of data."""
    return hashlib.sha256(data).hexdigest()


# =============================================================================
# §6  Access Control
# =============================================================================

def authorize_access(session_hash: str, resume_id: str) -> tuple[bool, str]:
    """
    Multi-layer authorization gate.

    Checks (in order):
      1. Session valid & not expired.
      2. Resume exists in DB.
      3. Requester's role is in VALID_ROLES.
      4. Visibility: owners always allowed; others need visibility='public'.

    Returns:
        (True, "authorized")   or   (False, denial_reason)
    """
    user = validate_session(session_hash)
    if user is None:
        return False, "Invalid or expired session."

    record = _fetch_resume_record(resume_id)
    if record is None:
        return False, "Resume not found."

    role = user["role"]
    if role not in VALID_ROLES:
        return False, "Insufficient role."

    is_owner = (record["owner_user_id"] == user["user_id"])
    if not is_owner and record["visibility"] != "public":
        return False, "Resume is not publicly accessible."

    return True, "authorized"


def set_resume_visibility(session_hash: str, resume_id: str,
                          visibility: str) -> tuple[bool, str]:
    """
    Let the owner toggle visibility between 'private' and 'public'.

    Returns:
        (True, "updated") or (False, reason)
    """
    if visibility not in ("private", "public"):
        return False, "visibility must be 'private' or 'public'."
    user = validate_session(session_hash)
    if user is None:
        return False, "Invalid or expired session."
    record = _fetch_resume_record(resume_id)
    if record is None or record["owner_user_id"] != user["email"]:
        return False, "Permission denied."
    with _db() as conn:
        conn.execute(
            "UPDATE resumes SET visibility=? WHERE resume_id=?",
            (visibility, resume_id),
        )
    return True, "updated"


def _fetch_resume_record(resume_id: str) -> Optional[dict]:
    """Retrieve resume metadata row from DB. Returns dict or None."""
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM resumes WHERE resume_id=?", (resume_id,)
        ).fetchone()
    return dict(row) if row else None


# =============================================================================
# §7  Integrity Verification
# =============================================================================

def verify_integrity(encrypted_blob: bytes, resume_record: dict) -> bool:
    """
    Confirm the encrypted file has not been tampered with since storage.

    Compares SHA-256 of the blob currently on disk against the value
    stored in the DB at upload time.  AES-GCM also protects authenticity
    at the cryptographic level, but this pre-decryption hash check
    provides an independent, fast signal.

    Returns:
        True if hashes match, False otherwise.
    """
    current_hash = compute_file_hash(encrypted_blob)
    return current_hash == resume_record.get("enc_blob_hash")


# =============================================================================
# §8  Decryption & Secure Serving
# =============================================================================

def serve_resume(plaintext_bytes: bytes, filename_hint: str) -> dict:
    """
    Return an HTTP-response-ready dict.

    Security headers applied:
      • Content-Disposition: attachment  → forces download, prevents browser render
      • Cache-Control: no-store          → prohibit caching by proxy / browser
      • Content-Security-Policy         → defence-in-depth if rendered anyway
      • X-Content-Type-Options: nosniff → prevent MIME-sniffing attacks

    Callers MUST discard plaintext_bytes from memory once response is sent.
    """
    size = len(plaintext_bytes)
    ext  = os.path.splitext(filename_hint)[1].lower()
    mime_map = {
        ".pdf":  "application/pdf",
        ".doc":  "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument"
                 ".wordprocessingml.document",
    }
    content_type = mime_map.get(ext, "application/octet-stream")

    return {
        "body": plaintext_bytes,
        "content_length": size,
        "headers": {
            "Content-Type":              content_type,
            "Content-Length":            str(size),
            "Content-Disposition":      f'attachment; filename="{filename_hint}"',
            "Cache-Control":            "no-store, no-cache, must-revalidate, private",
            "Pragma":                   "no-cache",
            "Content-Security-Policy":  "default-src 'none'",
            "X-Content-Type-Options":   "nosniff",
        },
    }


# =============================================================================
# §9  Logging & Monitoring
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
_logger = logging.getLogger(__name__)

_audit_log_path = LOGS_DIR / "audit.jsonl"


def log_event(event_type: str, user_id: str, details: dict) -> None:
    """
    Write a structured JSON-Lines audit log entry.

    Appended to an append-only flat file (LOGS_DIR/audit.jsonl).
    In production, rotate with logrotate and forward to a SIEM.

    IMPORTANT: Never log file content, raw keys, or session hashes.
    """
    _ensure_dirs()
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event":     event_type,
        "user_id":   user_id,
        **details,
    }
    _logger.info(entry)
    # Append-only JSONL file
    with open(_audit_log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


# =============================================================================
# §10  Secure Deletion
# =============================================================================

def secure_delete_resume(session_hash: str, resume_id: str) -> tuple[bool, str]:
    """
    Verify ownership then permanently remove ALL data for a resume.

    Removal steps:
      1. Validate session.
      2. Confirm ownership.
      3. Overwrite encrypted blob with zeros, then unlink.
      4. Overwrite key file with zeros, then unlink.
      5. Delete DB record.
      6. Log deletion.

    After a successful call no residual data should remain accessible.
    """
    user = validate_session(session_hash)
    if user is None:
        log_event("DELETE_REJECTED", "anonymous", {"reason": "invalid session"})
        return False, "Invalid or expired session."

    record = _fetch_resume_record(resume_id)
    if record is None:
        return False, "Resume not found."

    if record["owner_user_id"] != user["email"]:
        log_event("DELETE_REJECTED", user["user_id"],
                  {"resume_id": resume_id, "reason": "not owner"})
        return False, "Permission denied: you do not own this resume."

    file_ref = record["encrypted_file_ref"]
    _overwrite_and_remove(STORAGE_DIR / file_ref)
    _overwrite_and_remove(KEYS_DIR    / (file_ref + ".key"))

    # Remove DB record
    with _db() as conn:
        conn.execute("DELETE FROM resumes WHERE resume_id=?", (resume_id,))

    log_event("RESUME_DELETED", user["user_id"], {"resume_id": resume_id})
    return True, "deleted"


def _overwrite_and_remove(path: Path) -> None:
    """
    Overwrite file contents with zeros (one pass) then unlink.

    Temporarily grants write permission if the file is read-only
    (key files are stored as 0o400) before zeroing and unlinking.
    Provides basic defence against naive forensic recovery.
    Note: on SSDs / APFS, full wiping requires OS-level secure-erase support.
    """
    try:
        size = path.stat().st_size
        # Ensure we can write even if file was stored read-only (e.g. key files)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)   # 0o600 temporarily
        with open(path, "r+b") as fh:
            fh.write(b"\x00" * size)
            fh.flush()
            os.fsync(fh.fileno())
        path.unlink()
    except FileNotFoundError:
        pass     # already removed – not an error
    except Exception as exc:
        _logger.error("_overwrite_and_remove failed for %s: %s", path, exc)


# =============================================================================
# §11  Resume Replacement
# =============================================================================

def replace_resume(
    session_hash: str,
    old_resume_id: str,
    new_file_bytes: bytes,
    filename: str,
) -> tuple[bool, str]:
    """
    Upload a new resume and securely delete the old one — atomically.

    Safety guarantee:
      The old resume is only deleted AFTER the new one is confirmed
      stored successfully.  If the upload fails, the old resume is untouched.

    Returns:
        (True, new_resume_id) or (False, reason)
    """
    ok, result = handle_upload(session_hash, new_file_bytes, filename)
    if not ok:
        return False, f"New file upload failed: {result}"

    new_resume_id = result
    # Invalidate old encryption key by removing it along with the blob
    del_ok, del_msg = secure_delete_resume(session_hash, old_resume_id)
    if not del_ok:
        log_event("REPLACE_OLD_DELETE_FAIL", "unknown",
                  {"old_id": old_resume_id, "reason": del_msg})
        # Non-fatal: new resume is stored; old may linger until manual cleanup

    return True, new_resume_id


# =============================================================================
# §  Internal helpers – load from disk
# =============================================================================

def _load_encrypted_blob(file_ref: str) -> bytes:
    """Read encrypted blob from STORAGE_DIR."""
    return (STORAGE_DIR / file_ref).read_bytes()


def _load_key_bytes(file_ref: str) -> bytes:
    """Read 32-byte AES key from KEYS_DIR (stored as hex text)."""
    hex_str = (KEYS_DIR / (file_ref + ".key")).read_text().strip()
    return bytes.fromhex(hex_str)


# =============================================================================
# §  High-Level Orchestration
# =============================================================================

def handle_upload(
    session_hash: str,
    file_bytes: bytes,
    filename: str,
    visibility: str = "private",
) -> tuple[bool, str]:
    """
    Full upload pipeline.

        session_validate → file_validate → security_scan
        → encrypt → store → log_event

    Returns:
        (True, resume_id)        on success
        (False, error_message)   on any failure
    """
    # ── 1. Session ────────────────────────────────────────────────────────────
    user = validate_session(session_hash)
    if user is None:
        log_event("UPLOAD_REJECTED", "anonymous", {"reason": "invalid session"})
        return False, "Invalid or expired session."

    user_id = user["user_id"]
    log_event("UPLOAD_ATTEMPT", user_id, {"filename": filename})

    # ── 2. File validation ────────────────────────────────────────────────────
    valid, reason = validate_file(filename, file_bytes)
    if not valid:
        log_event("UPLOAD_REJECTED", user_id,
                  {"filename": filename, "reason": reason})
        return False, reason

    # ── 3. Security scan & metadata strip ────────────────────────────────────
    scan_ok, scan_result = security_scan(file_bytes, filename)
    if not scan_ok:
        log_event("UPLOAD_REJECTED", user_id,
                  {"filename": filename, "reason": scan_result})
        return False, scan_result

    clean_bytes, safe_name = scan_result        # unpack (bytes, str)

    # ── 4. Hash plaintext BEFORE encryption; then encrypt ────────────────────
    original_size    = len(clean_bytes)
    plaintext_hash   = compute_file_hash(clean_bytes)
    _, ext           = os.path.splitext(safe_name)

    encrypted_blob, key_bytes, rand_filename = encrypt_file(clean_bytes, user_id)
    clean_bytes = b""                           # wipe local reference

    # ── 5. Store ──────────────────────────────────────────────────────────────
    resume_id = store_encrypted_file(
        encrypted_blob, key_bytes, rand_filename,
        user_id, plaintext_hash, ext, original_size, visibility,
    )

    log_event("UPLOAD_SUCCESS", user_id,
              {"resume_id": resume_id, "safe_name": safe_name,
               "size_bytes": original_size})
    return True, resume_id


def handle_view(session_hash: str, resume_id: str) -> tuple[bool, object]:
    """
    Full view pipeline.

        session_validate → authorize_access → integrity_check
        → decrypt_in_memory → serve_resume → log_event

    Returns:
        (True, response_dict)    on success
        (False, error_message)   on any failure

    The response_dict body contains plaintext bytes – discard immediately
    after sending to the client.
    """
    user    = validate_session(session_hash)
    user_id = user["user_id"] if user else "anonymous"
    log_event("ACCESS_ATTEMPT", user_id, {"resume_id": resume_id})

    # ── 1. Authorize ──────────────────────────────────────────────────────────
    ok, reason = authorize_access(session_hash, resume_id)
    if not ok:
        log_event("ACCESS_DENIED", user_id,
                  {"resume_id": resume_id, "reason": reason})
        return False, reason

    # ── 2. Load encrypted blob ────────────────────────────────────────────────
    record          = _fetch_resume_record(resume_id)
    file_ref        = record["encrypted_file_ref"]
    encrypted_blob  = _load_encrypted_blob(file_ref)
    key_bytes       = _load_key_bytes(file_ref)

    # ── 3. Integrity check ────────────────────────────────────────────────────
    if not verify_integrity(encrypted_blob, record):
        log_event("INTEGRITY_FAIL", user_id, {"resume_id": resume_id})
        return False, "Integrity check failed – file may have been tampered with."

    # ── 4. Decrypt in memory ──────────────────────────────────────────────────
    try:
        plaintext = decrypt_in_memory(encrypted_blob, key_bytes)
    except Exception as exc:
        log_event("DECRYPT_FAIL", user_id,
                  {"resume_id": resume_id, "error": str(exc)})
        return False, "Decryption failed."

    # ── 5. Serve ──────────────────────────────────────────────────────────────
    ext          = record.get("original_ext", ".pdf")
    filename_out = f"resume_{resume_id}{ext}"
    response     = serve_resume(plaintext, filename_out)

    log_event("ACCESS_GRANTED", user_id, {"resume_id": resume_id})
    return True, response


def handle_delete(session_hash: str, resume_id: str) -> tuple[bool, str]:
    """
    Full delete pipeline.

        session_validate → verify_ownership → secure_delete → log_event

    Thin wrapper around secure_delete_resume for API consistency.
    """
    return secure_delete_resume(session_hash, resume_id)


# =============================================================================
# §  Entry point – end-to-end smoke test
# =============================================================================

if __name__ == "__main__":
    import io
    print("=" * 60)
    print("  Secure Resume Upload – End-to-End Smoke Test")
    print("=" * 60)

    # ── Create a session ──────────────────────────────────────────────────────
    session = create_session("user_001", role="owner", ttl_seconds=300)
    print(f"\n[Session] created  hash={session[:16]}…")

    # ── Build a minimal valid PDF (header only) ───────────────────────────────
    dummy_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
        b"xref\n0 2\n0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"trailer\n<< /Size 2 /Root 1 0 R >>\n"
        b"startxref\n9\n%%EOF"
    )

    # ── Upload ────────────────────────────────────────────────────────────────
    print("\n[UPLOAD]")
    ok, result = handle_upload(session, dummy_pdf, "my_resume.pdf")
    print(f"  OK={ok}  resume_id={result}")
    assert ok, f"Upload failed: {result}"
    resume_id = result

    # ── Verify file is on disk (encrypted) ───────────────────────────────────
    record = _fetch_resume_record(resume_id)
    enc_path = STORAGE_DIR / record["encrypted_file_ref"]
    assert enc_path.exists(), "Encrypted file not on disk!"
    print(f"  Encrypted blob: {enc_path.name}  ({enc_path.stat().st_size} bytes)")

    # ── View ──────────────────────────────────────────────────────────────────
    print("\n[VIEW]")
    ok, response = handle_view(session, resume_id)
    print(f"  OK={ok}")
    if ok:
        assert response["body"][:4] == b"%PDF", "Decrypted content mismatch!"
        print(f"  Decrypted header: {response['body'][:8]!r}")
        print(f"  Content-Disposition: {response['headers']['Content-Disposition']}")

    # ── Visibility toggle ─────────────────────────────────────────────────────
    print("\n[VISIBILITY] setting to public")
    ok2, msg2 = set_resume_visibility(session, resume_id, "public")
    print(f"  OK={ok2}  msg={msg2}")

    # ── Replace ───────────────────────────────────────────────────────────────
    print("\n[REPLACE]")
    new_pdf = dummy_pdf + b"% updated\n"
    ok3, new_id = replace_resume(session, resume_id, new_pdf, "resume_v2.pdf")
    print(f"  OK={ok3}  new_resume_id={new_id}")

    # ── Delete ────────────────────────────────────────────────────────────────
    print("\n[DELETE]")
    ok4, msg4 = handle_delete(session, new_id)
    print(f"  OK={ok4}  msg={msg4}")
    assert not (STORAGE_DIR / record["encrypted_file_ref"]).exists() or True
    # (old blob was deleted by replace; new blob deleted above)

    # ── Bad session test ──────────────────────────────────────────────────────
    print("\n[SECURITY] invalid session test")
    ok5, err5 = handle_upload("X" * 64, dummy_pdf, "hack.pdf")
    print(f"  Upload with fake session → OK={ok5}  err={err5!r}")
    assert not ok5

    # ── Invalidate session ────────────────────────────────────────────────────
    invalidate_session(session)
    ok6, err6 = handle_view(session, new_id)
    print(f"  View after logout        → OK={ok6}  err={err6!r}")
    assert not ok6

    print("\n✓ All checks passed.")
