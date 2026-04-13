from flask import Flask
from flask_cors import CORS

from core.db import setup_db

from routes.auth import bp as auth_bp
from routes.users import bp as users_bp
from routes.companies import bp as companies_bp
from routes.jobs import bp as jobs_bp
from routes.applications import bp as applications_bp
from routes.messages import bp as messages_bp
from routes.admin import bp as admin_bp
from routes.connections import bp as connections_bp
from routes.static_pages import bp as static_bp

app = Flask(__name__)
CORS(app, origins=["http://localhost:8000", "https://localhost"], supports_credentials=True)

# Initialize database
setup_db()

# ── CSRF Protection (global middleware) ─────────────────────────────────────
import hashlib
import secrets
import sqlite3
from flask import request, jsonify
from core.db import DB_NAME

# Endpoints exempt from CSRF validation (pre-authentication or non-state-changing)
CSRF_EXEMPT_PREFIXES = [
    '/api/v1/auth/',     # Login, register, logout — no session yet or session is being created
]

@app.before_request
def csrf_protect():
    """
    Global CSRF protection middleware.
    Validates the X-CSRF-Token header against the session's stored token
    for all state-changing requests (POST, PUT, DELETE, PATCH).
    Auth endpoints are exempt since the session/CSRF token doesn't exist yet.
    """
    if request.method not in ('POST', 'PUT', 'DELETE', 'PATCH'):
        return  # GET/HEAD/OPTIONS are safe
    
    # Exempt auth endpoints
    for prefix in CSRF_EXEMPT_PREFIXES:
        if request.path.startswith(prefix):
            return
    
    # Check for CSRF token header
    csrf_header = request.headers.get('X-CSRF-Token', '')
    if not csrf_header:
        return jsonify({"status": "error", "message": "Missing CSRF token"}), 403
    
    # Validate against session
    session_id = request.cookies.get('session_id')
    if not session_id:
        return  # Let require_auth handle the 401
    
    hashed_sid = hashlib.sha256(session_id.encode()).hexdigest()
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        session = conn.execute("SELECT csrf_token FROM sessions WHERE session_hash=?", (hashed_sid,)).fetchone()
        if session and session['csrf_token']:
            if not secrets.compare_digest(csrf_header, session['csrf_token']):
                return jsonify({"status": "error", "message": "Invalid CSRF token"}), 403
        # If no CSRF token in session (legacy sessions), allow through gracefully

# ── Register Blueprints ─────────────────────────────────────────────────────
# Register Blueprints with production-ready prefixes
app.register_blueprint(auth_bp, url_prefix='/api/v1/auth')
app.register_blueprint(users_bp, url_prefix='/api/v1/users')
app.register_blueprint(companies_bp, url_prefix='/api/v1/companies')
app.register_blueprint(jobs_bp, url_prefix='/api/v1/jobs')
app.register_blueprint(applications_bp, url_prefix='/api/v1/applications')
app.register_blueprint(messages_bp, url_prefix='/api/v1/messages')
app.register_blueprint(admin_bp, url_prefix='/api/v1/admin')
app.register_blueprint(connections_bp, url_prefix='/api/v1/connections')

# Register static routes
app.register_blueprint(static_bp)

if __name__ == '__main__':
    app.run(port=8000, debug=False)
