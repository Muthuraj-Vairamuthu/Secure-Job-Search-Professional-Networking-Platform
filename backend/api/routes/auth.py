import os
import sqlite3
import hashlib
import secrets
import hmac
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, make_response
from core.db import DB_NAME, get_client_ip, log_action, generate_csrf_token
import auth_secTOTP as auth_sec

# Point auth_secTOTP to the unified DB
auth_sec.DB_NAME = DB_NAME

bp = Blueprint('auth', __name__)
ALLOWED_SIGNUP_ROLES = {'user', 'recruiter', 'admin'}


def _signup_signature_secret():
    configured = os.getenv('SIGNUP_CONTEXT_SECRET', '').strip()
    if configured:
        return configured.encode('utf-8')
    return auth_sec.ENCRYPTION_KEY


def _normalize_signup_role(role):
    role = (role or 'user').strip().lower()
    return role if role in ALLOWED_SIGNUP_ROLES else 'user'


def _is_admin_signup_authorized(raw_code):
    expected_code = os.getenv('ADMIN_SIGNUP_CODE', '').strip()
    provided_code = (raw_code or '').strip()
    if not expected_code:
        return False
    return secrets.compare_digest(provided_code, expected_code)


def _build_signup_context_signature(context):
    payload = '|'.join([
        context.get('email', ''),
        context.get('password_hash', ''),
        context.get('mfa_secret_raw', ''),
        context.get('role', 'user'),
        context.get('name', ''),
        '1' if context.get('admin_signup_authorized') else '0'
    ])
    return hmac.new(_signup_signature_secret(), payload.encode('utf-8'), hashlib.sha256).hexdigest()


def _is_signup_context_valid(context):
    if not isinstance(context, dict):
        return False

    expected = _build_signup_context_signature(context)
    provided = context.get('signup_signature', '')
    if not provided:
        return False

    return hmac.compare_digest(provided, expected)


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


@bp.route('/register', methods=['POST'])
def register():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    role = _normalize_signup_role(data.get('role', 'user'))
    admin_signup_code = data.get('admin_signup_code', '')
    ip = get_client_ip()

    if role == 'admin' and not _is_admin_signup_authorized(admin_signup_code):
        return jsonify({
            "status": "error",
            "message": "Admin signup requires a valid admin access code."
        }), 403

    res = auth_sec.signup_step_1(email, password, ip)
    if res['status'] == 'pending_mfa_setup':
        res['context']['role'] = role
        res['context']['name'] = data.get('name', '')
        res['context']['admin_signup_authorized'] = role == 'admin'
        res['context']['signup_signature'] = _build_signup_context_signature(res['context'])
    return jsonify(res)

@bp.route('/register/verify', methods=['POST'])
def register_verify():
    data = request.json
    context = data.get('context')
    totp_code = data.get('totp_code')
    ip = get_client_ip()

    if not _is_signup_context_valid(context):
        return jsonify({"status": "error", "message": "Signup session is invalid or has been tampered with."}), 400

    role = _normalize_signup_role(context.get('role', 'user'))
    if role == 'admin' and not context.get('admin_signup_authorized'):
        return jsonify({"status": "error", "message": "Admin signup is not authorized."}), 403

    res = auth_sec.signup_step_2(context, totp_code, ip)
    if res['status'] == 'success':
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


@bp.route('/forgot-password/reset', methods=['POST'])
def forgot_password_reset():
    data = request.json or {}
    email = data.get('email', '').strip()
    totp_code = data.get('totp_code', '').strip()
    new_password = data.get('new_password', '')
    ip = get_client_ip()

    if not email or not totp_code or not new_password:
        return jsonify({"status": "error", "message": "Email, authenticator code, and new password are required."}), 400

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
            return jsonify({"status": "error", "message": "Password recovery is available only for verified accounts with an authenticator app configured."}), 400

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
        conn.execute("DELETE FROM sessions WHERE user_id=?", (email,))
        conn.execute("DELETE FROM mfa_pending_sessions WHERE email=?", (email,))
        conn.commit()

    log_action(email, "PASSWORD_RESET_COMPLETED_VIA_TOTP")
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
