import sqlite3
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from core.db import DB_NAME, require_auth, require_recruiter, log_action

bp = Blueprint('companies', __name__)

@bp.route('', methods=['POST'])
@require_auth
@require_recruiter
def create_company(user_id):
    data = request.json
    name = data.get('name', '').strip()
    if not name:
        return jsonify({"status": "error", "message": "Company name is required"}), 400
    description = data.get('description', '').strip()
    location = data.get('location', '').strip()
    website = data.get('website', '').strip()
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute(
            "INSERT INTO companies (name, description, location, website, owner_email, created_at) VALUES (?,?,?,?,?,?)",
            (name, description, location, website, user_id, now)
        )
        company_id = cursor.lastrowid
    log_action(user_id, f"COMPANY_CREATED: {name}")
    return jsonify({"status": "success", "company_id": company_id, "message": "Company created"})

@bp.route('', methods=['GET'])
@require_auth
def list_companies(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        companies = conn.execute(
            "SELECT c.*, (SELECT COUNT(*) FROM jobs j WHERE j.company_id=c.id AND j.status='active') as active_jobs FROM companies c ORDER BY c.created_at DESC"
        ).fetchall()
    return jsonify({"status": "success", "companies": [dict(c) for c in companies]})

@bp.route('/<int:company_id>', methods=['GET'])
@require_auth
def get_company(user_id, company_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        company = conn.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
        if not company:
            return jsonify({"status": "error", "message": "Company not found"}), 404
        jobs = conn.execute(
            "SELECT * FROM jobs WHERE company_id=? ORDER BY created_at DESC", (company_id,)
        ).fetchall()
    return jsonify({
        "status": "success",
        "company": dict(company),
        "jobs": [dict(j) for j in jobs]
    })

@bp.route('/<int:company_id>', methods=['PUT'])
@require_auth
@require_recruiter
def update_company(user_id, company_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        company = conn.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
    if not company:
        return jsonify({"status": "error", "message": "Company not found"}), 404
    if company['owner_email'] != user_id:
        return jsonify({"status": "error", "message": "Permission denied"}), 403
    data = request.json
    allowed = {'name', 'description', 'location', 'website'}
    updates = {k: v for k, v in data.items() if k in allowed and isinstance(v, str)}
    if not updates:
        return jsonify({"status": "error", "message": "No valid fields"}), 400
    set_clause = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [company_id]
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(f"UPDATE companies SET {set_clause} WHERE id=?", values)
    log_action(user_id, f"COMPANY_UPDATED: id={company_id}")
    return jsonify({"status": "success", "message": "Company updated"})

@bp.route('/me', methods=['GET'])
@require_auth
@require_recruiter
def my_companies(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        companies = conn.execute(
            "SELECT c.*, (SELECT COUNT(*) FROM jobs j WHERE j.company_id=c.id) as total_jobs FROM companies c WHERE c.owner_email=? ORDER BY c.created_at DESC",
            (user_id,)
        ).fetchall()
    return jsonify({"status": "success", "companies": [dict(c) for c in companies]})
