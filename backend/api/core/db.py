import os
import sqlite3
import hashlib
import secrets
from datetime import datetime, timezone
from functools import wraps
from flask import request, jsonify

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../data'))
DB_NAME = os.path.join(DATA_DIR, "secure_app.db")
AUDIT_BLOCK_SIZE = 3
AUDIT_BLOCK_DIFFICULTY_PREFIX = "000"

def setup_db():
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            bio TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '',
            headline TEXT NOT NULL DEFAULT '',
            skills TEXT NOT NULL DEFAULT '',
            education TEXT NOT NULL DEFAULT '',
            experience TEXT NOT NULL DEFAULT '',
            profile_picture_url TEXT NOT NULL DEFAULT '',
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            is_verified BOOLEAN NOT NULL DEFAULT 0,
            failed_attempts INTEGER NOT NULL DEFAULT 0,
            locked_until TIMESTAMP,
            mfa_enabled BOOLEAN NOT NULL DEFAULT 0,
            mfa_secret TEXT,
            last_mfa_window INTEGER DEFAULT 0,
            privacy_profile TEXT NOT NULL DEFAULT 'public',
            show_profile_views BOOLEAN NOT NULL DEFAULT 1,
            pki_private_key TEXT DEFAULT '',
            pki_public_key TEXT DEFAULT ''
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS mfa_pending_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_hash TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_hash TEXT NOT NULL UNIQUE,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            client_ip TEXT NOT NULL DEFAULT '',
            user_agent TEXT NOT NULL DEFAULT '',
            csrf_token TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP NOT NULL,
            expires_at TIMESTAMP NOT NULL
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS verification_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            token_hash TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            event TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            prev_hash TEXT NOT NULL DEFAULT '',
            log_hash TEXT NOT NULL DEFAULT ''
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS log_blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_log_id INTEGER NOT NULL,
            end_log_id INTEGER NOT NULL,
            entry_count INTEGER NOT NULL,
            merkle_root TEXT NOT NULL,
            prev_block_hash TEXT NOT NULL DEFAULT 'GENESIS',
            nonce INTEGER NOT NULL DEFAULT 0,
            authority TEXT NOT NULL DEFAULT 'FCS19',
            block_hash TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS resumes (
            resume_id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            encrypted_file_ref TEXT NOT NULL UNIQUE,
            file_hash TEXT NOT NULL,
            enc_blob_hash TEXT NOT NULL,
            upload_timestamp TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            original_ext TEXT NOT NULL,
            visibility TEXT NOT NULL DEFAULT 'private',
            digital_signature TEXT DEFAULT '',
            parsed_text TEXT DEFAULT '',
            parsed_skills TEXT DEFAULT ''
        )''')

        # Companies: Created by recruiters
        c.execute('''CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '',
            website TEXT NOT NULL DEFAULT '',
            owner_email TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL,
            FOREIGN KEY (owner_email) REFERENCES users(email)
        )''')

        # Jobs: Posted under a company by recruiters
        c.execute('''CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            skills TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '',
            job_type TEXT NOT NULL DEFAULT 'full-time',
            salary_min INTEGER,
            salary_max INTEGER,
            deadline TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMP NOT NULL,
            FOREIGN KEY (company_id) REFERENCES companies(id)
        )''')

        # Applications: Users apply to jobs
        c.execute('''CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            applicant_email TEXT NOT NULL,
            resume_id TEXT,
            cover_note TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Applied',
            recruiter_notes TEXT NOT NULL DEFAULT '',
            applied_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs(id),
            FOREIGN KEY (applicant_email) REFERENCES users(email),
            UNIQUE(job_id, applicant_email)
        )''')

        # Conversations: Direct (1-to-1) or group chats
        c.execute('''CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL DEFAULT 'direct',
            name TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP NOT NULL,
            created_by TEXT NOT NULL,
            FOREIGN KEY (created_by) REFERENCES users(email)
        )''')

        # Conversation Members: Who is in each conversation
        c.execute('''CREATE TABLE IF NOT EXISTS conversation_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            user_email TEXT NOT NULL,
            public_key TEXT NOT NULL DEFAULT '',
            joined_at TIMESTAMP NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (user_email) REFERENCES users(email),
            UNIQUE(conversation_id, user_email)
        )''')

        # Messages: Only ciphertext stored (E2EE)
        c.execute('''CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            sender_email TEXT NOT NULL,
            encrypted_content TEXT NOT NULL,
            iv TEXT NOT NULL DEFAULT '',
            signature TEXT NOT NULL DEFAULT '',
            timestamp TIMESTAMP NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (sender_email) REFERENCES users(email)
        )''')

        # Connections: Professional connections between users
        c.execute('''CREATE TABLE IF NOT EXISTS connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requester_email TEXT NOT NULL,
            recipient_email TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            FOREIGN KEY (requester_email) REFERENCES users(email),
            FOREIGN KEY (recipient_email) REFERENCES users(email),
            UNIQUE(requester_email, recipient_email)
        )''')

        # Profile Views: Track who viewed whose profile
        c.execute('''CREATE TABLE IF NOT EXISTS profile_views (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            viewer_email TEXT NOT NULL,
            viewed_email TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            FOREIGN KEY (viewer_email) REFERENCES users(email),
            FOREIGN KEY (viewed_email) REFERENCES users(email)
        )''')

        # Migration: add privacy columns if missing (for existing DBs)
        try:
            c.execute("ALTER TABLE users ADD COLUMN privacy_profile TEXT NOT NULL DEFAULT 'public'")
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE users ADD COLUMN show_profile_views BOOLEAN NOT NULL DEFAULT 1")
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE users ADD COLUMN skills TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE users ADD COLUMN education TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE users ADD COLUMN experience TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE users ADD COLUMN profile_picture_url TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass
        # Migration: PKI columns
        try:
            c.execute("ALTER TABLE users ADD COLUMN pki_private_key TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE users ADD COLUMN pki_public_key TEXT DEFAULT ''")
        except Exception:
            pass
        # Migration: digital_signature on resumes
        try:
            c.execute("ALTER TABLE resumes ADD COLUMN digital_signature TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE resumes ADD COLUMN parsed_text TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE resumes ADD COLUMN parsed_skills TEXT DEFAULT ''")
        except Exception:
            pass
        # Migration: signature on messages
        try:
            c.execute("ALTER TABLE messages ADD COLUMN signature TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass
        # Migration: hash chaining on audit_logs
        try:
            c.execute("ALTER TABLE audit_logs ADD COLUMN prev_hash TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE audit_logs ADD COLUMN log_hash TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE log_blocks ADD COLUMN authority TEXT NOT NULL DEFAULT 'FCS19'")
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE log_blocks ADD COLUMN nonce INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
        # Migration: session binding columns
        try:
            c.execute("ALTER TABLE sessions ADD COLUMN client_ip TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE sessions ADD COLUMN user_agent TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass
        # Migration: CSRF token on sessions
        try:
            c.execute("ALTER TABLE sessions ADD COLUMN csrf_token TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass

        conn.commit()

def get_client_ip():
    return request.headers.get('X-Forwarded-For', request.remote_addr)

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        session_id = request.cookies.get('session_id')
        if not session_id:
            return jsonify({"status": "error", "message": "Unauthorized"}), 401
        hashed_sid = hashlib.sha256(session_id.encode()).hexdigest()
        with sqlite3.connect(DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            session = conn.execute("SELECT * FROM sessions WHERE session_hash=?", (hashed_sid,)).fetchone()
        if not session:
            return jsonify({"status": "error", "message": "Invalid session"}), 401
        if datetime.now(timezone.utc) > datetime.fromisoformat(session['expires_at']):
            return jsonify({"status": "error", "message": "Session expired"}), 401
        # Session binding: validate IP + User-Agent if they were stored
        if session['client_ip'] and session['client_ip'] != get_client_ip():
            log_action_raw(session['user_id'], f"SESSION_IP_MISMATCH: expected={session['client_ip']}, got={get_client_ip()}")
            return jsonify({"status": "error", "message": "Session invalidated: IP address changed"}), 401
        stored_ua = session['user_agent'] if 'user_agent' in session.keys() else ''
        current_ua = request.headers.get('User-Agent', '')
        if stored_ua and stored_ua != current_ua:
            log_action_raw(session['user_id'], "SESSION_UA_MISMATCH")
            return jsonify({"status": "error", "message": "Session invalidated: device changed"}), 401
        return f(session['user_id'], *args, **kwargs)
    return decorated


def generate_csrf_token():
    """Generate a cryptographically secure CSRF token."""
    return secrets.token_hex(32)


def require_csrf(f):
    """
    Decorator to enforce CSRF validation on state-changing requests (POST/PUT/DELETE).
    The client must send the CSRF token as the 'X-CSRF-Token' header.
    The token is compared against the one stored in the user's session.
    Stack AFTER @require_auth: @require_auth, then @require_csrf.
    """
    @wraps(f)
    def decorated(user_id, *args, **kwargs):
        # Only enforce on state-changing methods
        if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            csrf_header = request.headers.get('X-CSRF-Token', '')
            if not csrf_header:
                return jsonify({"status": "error", "message": "Missing CSRF token"}), 403
            # Look up the session's CSRF token
            session_id = request.cookies.get('session_id')
            if session_id:
                hashed_sid = hashlib.sha256(session_id.encode()).hexdigest()
                with sqlite3.connect(DB_NAME) as conn:
                    conn.row_factory = sqlite3.Row
                    session = conn.execute("SELECT csrf_token FROM sessions WHERE session_hash=?", (hashed_sid,)).fetchone()
                    if session and session['csrf_token']:
                        if not secrets.compare_digest(csrf_header, session['csrf_token']):
                            return jsonify({"status": "error", "message": "Invalid CSRF token"}), 403
                    else:
                        # No CSRF token in session (legacy) — skip validation
                        pass
        return f(user_id, *args, **kwargs)
    return decorated

def require_recruiter(f):
    @wraps(f)
    def decorated(user_id, *args, **kwargs):
        with sqlite3.connect(DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            user = conn.execute("SELECT role FROM users WHERE email=?", (user_id,)).fetchone()
        if not user or user['role'] != 'recruiter':
            return jsonify({"status": "error", "message": "Forbidden. Recruiters only."}), 403
        return f(user_id, *args, **kwargs)
    return decorated

def require_admin(f):
    @wraps(f)
    def decorated(user_id, *args, **kwargs):
        with sqlite3.connect(DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            user = conn.execute("SELECT role FROM users WHERE email=?", (user_id,)).fetchone()
        if not user or user['role'] != 'admin':
            return jsonify({"status": "error", "message": "Forbidden. Admins only."}), 403
        return f(user_id, *args, **kwargs)
    return decorated

def log_action(email, action):
    """Insert an audit log entry with hash chaining for tamper evidence."""
    ip = get_client_ip()
    insert_audit_log_entry(email, action, ip)


def log_action_raw(email, action):
    """Insert audit log without Flask request context (for session binding violations)."""
    try:
        ip = get_client_ip()
    except RuntimeError:
        ip = 'unknown'
    insert_audit_log_entry(email, action, ip)


def insert_audit_log_entry(email, action, ip_address='unknown'):
    ts = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        _insert_audit_log_entry(conn, email, action, ip_address, ts)
        _maybe_finalize_audit_blocks(conn)
        conn.commit()


def _insert_audit_log_entry(conn, email, action, ip_address, timestamp):
    last = conn.execute("SELECT log_hash FROM audit_logs ORDER BY id DESC LIMIT 1").fetchone()
    prev_hash = last['log_hash'] if last and last['log_hash'] else 'GENESIS'
    chain_input = f"{prev_hash}|{email}|{action}|{timestamp}|{ip_address}"
    log_hash = hashlib.sha256(chain_input.encode('utf-8')).hexdigest()
    conn.execute(
        "INSERT INTO audit_logs (email, ip_address, event, timestamp, prev_hash, log_hash) VALUES (?, ?, ?, ?, ?, ?)",
        (email, ip_address, action, timestamp, prev_hash, log_hash)
    )


def finalize_audit_blocks(force=False):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        created = _maybe_finalize_audit_blocks(conn, force=force)
        conn.commit()
    return created


def _maybe_finalize_audit_blocks(conn, force=False):
    created_blocks = 0
    while True:
        last_block = conn.execute("SELECT end_log_id FROM log_blocks ORDER BY id DESC LIMIT 1").fetchone()
        last_end_id = last_block['end_log_id'] if last_block else 0
        pending = conn.execute(
            "SELECT id, log_hash FROM audit_logs WHERE id > ? ORDER BY id ASC",
            (last_end_id,)
        ).fetchall()

        if not pending:
            break
        if len(pending) < AUDIT_BLOCK_SIZE and not force:
            break

        block_entries = pending if force and len(pending) < AUDIT_BLOCK_SIZE else pending[:AUDIT_BLOCK_SIZE]
        _create_audit_block(conn, block_entries)
        created_blocks += 1

        if force and len(block_entries) == len(pending):
            break
    return created_blocks


def _create_audit_block(conn, block_entries):
    start_log_id = block_entries[0]['id']
    end_log_id = block_entries[-1]['id']
    entry_count = len(block_entries)
    merkle_root = _build_merkle_root([entry['log_hash'] for entry in block_entries])
    previous_block = conn.execute(
        "SELECT block_hash FROM log_blocks ORDER BY id DESC LIMIT 1"
    ).fetchone()
    prev_block_hash = previous_block['block_hash'] if previous_block and previous_block['block_hash'] else 'GENESIS'
    created_at = datetime.now(timezone.utc).isoformat()
    nonce, block_hash = _mine_block_hash(prev_block_hash, start_log_id, end_log_id, entry_count, merkle_root, created_at)
    conn.execute(
        """INSERT INTO log_blocks
           (start_log_id, end_log_id, entry_count, merkle_root, prev_block_hash, nonce, authority, block_hash, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (start_log_id, end_log_id, entry_count, merkle_root, prev_block_hash, nonce, 'FCS19', block_hash, created_at)
    )


def _build_merkle_root(hashes):
    if not hashes:
        return hashlib.sha256(b'').hexdigest()

    level = list(hashes)
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        next_level = []
        for i in range(0, len(level), 2):
            pair = f"{level[i]}|{level[i + 1]}"
            next_level.append(hashlib.sha256(pair.encode('utf-8')).hexdigest())
        level = next_level
    return level[0]


def _mine_block_hash(prev_block_hash, start_log_id, end_log_id, entry_count, merkle_root, created_at):
    nonce = 0
    while True:
        block_hash = _compute_block_hash(prev_block_hash, start_log_id, end_log_id, entry_count, merkle_root, created_at, nonce)
        if block_hash.startswith(AUDIT_BLOCK_DIFFICULTY_PREFIX):
            return nonce, block_hash
        nonce += 1


def _compute_block_hash(prev_block_hash, start_log_id, end_log_id, entry_count, merkle_root, created_at, nonce):
    payload = f"{prev_block_hash}|{start_log_id}|{end_log_id}|{entry_count}|{merkle_root}|{created_at}|{nonce}|FCS19"
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()
