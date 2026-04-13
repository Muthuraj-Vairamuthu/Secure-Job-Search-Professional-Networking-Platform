import os
import sqlite3
import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, make_response
from core.db import DB_NAME, get_client_ip, log_action, generate_csrf_token
import auth_secTOTP as auth_sec

# Point auth_secTOTP to the unified DB
auth_sec.DB_NAME = DB_NAME

bp = Blueprint('auth', __name__)


def _simulate_verification_email(email, token):
    """
    Development-only email delivery mock.
    Writes the verification token to stdout and the shared server log.
    """
    message = f"[SIMULATED EMAIL] Verification token for {email}: {token}"
    print(message, flush=True)

    log_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../data/server.log'))
    try:
        with open(log_path, 'a', encoding='utf-8') as log_file:
            log_file.write(message + "\n")
    except OSError:
        pass


def _simulate_password_reset_email(email, token):
    """
    Development-only password reset delivery mock.
    Writes the reset token to stdout and the shared server log.
    """
    message = f"[SIMULATED EMAIL] Password reset token for {email}: {token}"
    print(message, flush=True)

    log_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../data/server.log'))
    try:
        with open(log_path, 'a', encoding='utf-8') as log_file:
            log_file.write(message + "\n")
    except OSError:
        pass


def _find_valid_password_reset_token(conn, email, raw_token):
    candidates = conn.execute(
        "SELECT id, token_hash, expires_at FROM password_reset_tokens WHERE email=?",
        (email,)
    ).fetchall()

    matched_token_id = None
    expired_token_ids = []
    now = datetime.now(timezone.utc)

    for token_row in candidates:
        expires_at = datetime.fromisoformat(token_row['expires_at'])
        if now > expires_at:
            expired_token_ids.append(token_row['id'])
            continue

        try:
            if auth_sec.ph.verify(token_row['token_hash'], raw_token):
                matched_token_id = token_row['id']
                break
        except Exception:
            continue

    for token_id in expired_token_ids:
        conn.execute("DELETE FROM password_reset_tokens WHERE id=?", (token_id,))

    return matched_token_id

@bp.route('/register', methods=['POST'])
def register():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    role = data.get('role', 'user')
    ip = get_client_ip()
    res = auth_sec.signup_step_1(email, password, ip)
    if res['status'] == 'pending_mfa_setup':
        res['context']['role'] = role
        res['context']['name'] = data.get('name', '')
    return jsonify(res)

@bp.route('/register/verify', methods=['POST'])
def register_verify():
    data = request.json
    context = data.get('context')
    totp_code = data.get('totp_code')
    ip = get_client_ip()
    res = auth_sec.signup_step_2(context, totp_code, ip)
    if res['status'] == 'success':
        role = context.get('role', 'user')
        name = context.get('name', '')
        email = context.get('email')
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("UPDATE users SET role=?, name=? WHERE email=?", (role, name, email))
        verification_token = res.get('email_verification_token', '')
        if verification_token:
            _simulate_verification_email(email, verification_token)
        return jsonify({
            "status": "success",
            "message": "Registration complete. Check the simulated email token to verify your account before login.",
            "email": email,
            "verification_required": True,
            "delivery_method": "console_log",
            "verification_token_preview": verification_token
        })
    return jsonify(res)


@bp.route('/verify-email', methods=['POST'])
def verify_email():
    data = request.json or {}
    email = data.get('email', '').strip()
    token = data.get('token', '').strip()
    ip = get_client_ip()
    res = auth_sec.verify_email_token(email, token, ip)
    return jsonify(res), (200 if res.get('status') == 'success' else 400)


@bp.route('/forgot-password/request', methods=['POST'])
def forgot_password_request():
    data = request.json or {}
    email = data.get('email', '').strip()
    ip = get_client_ip()

    generic_response = {
        "status": "success",
        "message": "If that account exists, a password reset token has been sent to the simulated delivery log."
    }

    if not email or len(email) > 255:
        return jsonify(generic_response)

    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        user = conn.execute(
            "SELECT email, is_verified, mfa_enabled, mfa_secret FROM users WHERE email=?",
            (email,)
        ).fetchone()

        if user and user['is_verified'] and user['mfa_enabled'] and user['mfa_secret']:
            raw_token = secrets.token_urlsafe(32)
            expiry = datetime.now(timezone.utc) + timedelta(minutes=15)

            conn.execute("DELETE FROM password_reset_tokens WHERE email=?", (email,))
            conn.execute(
                "INSERT INTO password_reset_tokens (email, token_hash, expires_at) VALUES (?, ?, ?)",
                (email, auth_sec.ph.hash(raw_token), expiry.isoformat())
            )
            conn.commit()

            _simulate_password_reset_email(email, raw_token)
            log_action(email, "PASSWORD_RESET_REQUESTED")

    return jsonify(generic_response)


@bp.route('/forgot-password/reset', methods=['POST'])
def forgot_password_reset():
    data = request.json or {}
    email = data.get('email', '').strip()
    reset_token = data.get('token', '').strip()
    totp_code = data.get('totp_code', '').strip()
    new_password = data.get('new_password', '')
    ip = get_client_ip()

    if not email or not reset_token or not totp_code or not new_password:
        return jsonify({"status": "error", "message": "Email, reset token, authenticator code, and new password are required."}), 400

    if len(email) > 255 or len(new_password) > 128:
        return jsonify({"status": "error", "message": "Invalid password reset request."}), 400

    dummy_email = "a@b.com"
    if not auth_sec.validate_inputs(dummy_email, new_password):
        return jsonify({"status": "error", "message": "New password does not meet the password policy."}), 400

    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        user = conn.execute(
            "SELECT email, mfa_secret, mfa_enabled FROM users WHERE email=? AND is_verified=1",
            (email,)
        ).fetchone()

        if not user or not user['mfa_enabled'] or not user['mfa_secret']:
            return jsonify({"status": "error", "message": "Invalid or expired password reset request."}), 400

        matched_token_id = _find_valid_password_reset_token(conn, email, reset_token)
        if matched_token_id is None:
            return jsonify({"status": "error", "message": "Invalid or expired password reset token."}), 400

        try:
            decrypted_secret = auth_sec.decrypt_data(user['mfa_secret'])
        except Exception:
            return jsonify({"status": "error", "message": "Unable to verify your authenticator code right now."}), 500

        totp = auth_sec.pyotp.TOTP(decrypted_secret)
        if not totp.verify(totp_code):
            auth_sec.handle_failed_login(email, ip)
            return jsonify({"status": "error", "message": "Invalid authenticator code."}), 400

        new_password_hash = auth_sec.ph.hash(new_password)
        conn.execute(
            "UPDATE users SET password_hash=?, failed_attempts=0, locked_until=NULL WHERE email=?",
            (new_password_hash, email)
        )
        conn.execute("DELETE FROM password_reset_tokens WHERE email=?", (email,))
        conn.execute("DELETE FROM sessions WHERE user_id=?", (email,))
        conn.execute("DELETE FROM mfa_pending_sessions WHERE email=?", (email,))
        conn.commit()

    log_action(email, "PASSWORD_RESET_COMPLETED")
    return jsonify({
        "status": "success",
        "message": "Password reset successful. Please log in with your new password."
    })

@bp.route('/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    ip = get_client_ip()
    res = auth_sec.login_step_1(email, password, ip)
    return jsonify(res)

@bp.route('/login/verify', methods=['POST'])
def login_verify():
    data = request.json
    mfa_token = data.get('mfa_token')
    totp_code = data.get('totp_code')
    ip = get_client_ip()
    res = auth_sec.login_step_2(mfa_token, totp_code, ip)
    if res['status'] == 'success':
        session_id = res['session_token']
        hashed_sid = hashlib.sha256(session_id.encode()).hexdigest()
        role = 'user'
        client_ip = get_client_ip()
        user_agent = request.headers.get('User-Agent', '')
        csrf_token = generate_csrf_token()
        with sqlite3.connect(DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT u.role FROM sessions s JOIN users u ON s.user_id = u.email WHERE s.session_hash=?",
                (hashed_sid,)
            ).fetchone()
            if row:
                role = row['role']
            # Bind session to client IP, User-Agent, and CSRF token
            conn.execute(
                "UPDATE sessions SET role=?, client_ip=?, user_agent=?, csrf_token=? WHERE session_hash=?",
                (role, client_ip, user_agent, csrf_token, hashed_sid)
            )
            conn.commit()
        resp = make_response(jsonify({"status": "success", "role": role}))
        resp.set_cookie('session_id', session_id, httponly=True, secure=True, samesite='Strict', max_age=1800)
        # CSRF token cookie: readable by JavaScript (not httponly) so frontend can send it as header
        resp.set_cookie('csrf_token', csrf_token, httponly=False, secure=True, samesite='Strict', max_age=1800)
        return resp
    return jsonify(res)

@bp.route('/session/rotate', methods=['POST'])
def rotate_session():
    """Rotate session ID (e.g., after privilege elevation). Preserves user binding."""
    old_session_id = request.cookies.get('session_id')
    if not old_session_id:
        return jsonify({"status": "error", "message": "No active session"}), 401

    old_hash = hashlib.sha256(old_session_id.encode()).hexdigest()
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        old_session = conn.execute("SELECT * FROM sessions WHERE session_hash=?", (old_hash,)).fetchone()
        if not old_session:
            return jsonify({"status": "error", "message": "Invalid session"}), 401

        # Generate new session ID and new CSRF token
        new_session_id = secrets.token_hex(32)
        new_hash = hashlib.sha256(new_session_id.encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        client_ip = get_client_ip()
        user_agent = request.headers.get('User-Agent', '')
        csrf_token = generate_csrf_token()

        # Delete old session, create new one with same user but new token
        conn.execute("DELETE FROM sessions WHERE session_hash=?", (old_hash,))
        conn.execute(
            "INSERT INTO sessions (session_hash, user_id, role, client_ip, user_agent, csrf_token, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?)",
            (new_hash, old_session['user_id'], old_session['role'], client_ip, user_agent, csrf_token, now, expires)
        )
        conn.commit()

    log_action(old_session['user_id'], "SESSION_ROTATED")
    resp = make_response(jsonify({"status": "success", "message": "Session rotated"}))
    resp.set_cookie('session_id', new_session_id, httponly=True, secure=True, samesite='Strict', max_age=1800)
    resp.set_cookie('csrf_token', csrf_token, httponly=False, secure=True, samesite='Strict', max_age=1800)
    return resp

@bp.route('/logout', methods=['POST'])
def logout():
    session_id = request.cookies.get('session_id')
    if session_id:
        hashed_sid = hashlib.sha256(session_id.encode()).hexdigest()
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("DELETE FROM sessions WHERE session_hash=?", (hashed_sid,))
    resp = make_response(jsonify({"status": "success"}))
    resp.set_cookie('session_id', '', expires=0)
    resp.set_cookie('csrf_token', '', expires=0)
    return resp
