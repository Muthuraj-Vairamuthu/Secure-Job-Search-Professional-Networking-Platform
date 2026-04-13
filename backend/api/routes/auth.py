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
