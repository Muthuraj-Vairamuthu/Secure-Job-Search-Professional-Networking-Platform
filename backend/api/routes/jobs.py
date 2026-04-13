import sqlite3
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from core.db import DB_NAME, require_auth, require_recruiter, log_action

bp = Blueprint('jobs', __name__)

@bp.route('', methods=['POST'])
@require_auth
@require_recruiter
def create_job(user_id):
    data = request.json
    company_id = data.get('company_id')
    title = data.get('title', '').strip()
    if not company_id or not title:
        return jsonify({"status": "error", "message": "company_id and title are required"}), 400
    # Verify recruiter owns this company
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        company = conn.execute("SELECT * FROM companies WHERE id=? AND owner_email=?", (company_id, user_id)).fetchone()
    if not company:
        return jsonify({"status": "error", "message": "Company not found or not owned by you"}), 403
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute(
            """INSERT INTO jobs (company_id, title, description, skills, location, job_type, salary_min, salary_max, deadline, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (company_id, title, data.get('description', ''), data.get('skills', ''),
             data.get('location', ''), data.get('job_type', 'full-time'),
             data.get('salary_min'), data.get('salary_max'),
             data.get('deadline', ''), 'active', now)
        )
        job_id = cursor.lastrowid
    log_action(user_id, f"JOB_POSTED: {title} (id={job_id})")
    return jsonify({"status": "success", "job_id": job_id, "message": "Job posted"})

@bp.route('', methods=['GET'])
@require_auth
def list_jobs(user_id):
    keyword = request.args.get('keyword', '').strip()
    location = request.args.get('location', '').strip()
    job_type = request.args.get('job_type', '').strip()
    company_name = request.args.get('company', '').strip()

    query = """SELECT j.*, c.name as company_name, c.location as company_location,
               (SELECT COUNT(*) FROM applications a WHERE a.job_id=j.id) as applicant_count
               FROM jobs j JOIN companies c ON j.company_id=c.id
               WHERE j.status='active'"""
    params = []

    if keyword:
        query += " AND (j.title LIKE ? OR j.description LIKE ? OR j.skills LIKE ?)"
        kw = f"%{keyword}%"
        params.extend([kw, kw, kw])
    if location:
        query += " AND (j.location LIKE ? OR c.location LIKE ?)"
        loc = f"%{location}%"
        params.extend([loc, loc])
    if job_type:
        query += " AND j.job_type=?"
        params.append(job_type)
    if company_name:
        query += " AND c.name LIKE ?"
        params.append(f"%{company_name}%")

    query += " ORDER BY j.created_at DESC"

    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        jobs = conn.execute(query, params).fetchall()
    return jsonify({"status": "success", "jobs": [dict(j) for j in jobs]})

@bp.route('/<int:job_id>', methods=['GET'])
@require_auth
def get_job(user_id, job_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        job = conn.execute(
            "SELECT j.*, c.name as company_name, c.location as company_location, c.website as company_website, c.description as company_description FROM jobs j JOIN companies c ON j.company_id=c.id WHERE j.id=?",
            (job_id,)
        ).fetchone()
    if not job:
        return jsonify({"status": "error", "message": "Job not found"}), 404
    return jsonify({"status": "success", "job": dict(job)})

@bp.route('/<int:job_id>', methods=['PUT'])
@require_auth
@require_recruiter
def update_job(user_id, job_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        job = conn.execute(
            "SELECT j.*, c.owner_email FROM jobs j JOIN companies c ON j.company_id=c.id WHERE j.id=?",
            (job_id,)
        ).fetchone()
    if not job:
        return jsonify({"status": "error", "message": "Job not found"}), 404
    if job['owner_email'] != user_id:
        return jsonify({"status": "error", "message": "Permission denied"}), 403
    data = request.json
    allowed = {'title', 'description', 'skills', 'location', 'job_type', 'salary_min', 'salary_max', 'deadline', 'status'}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"status": "error", "message": "No valid fields"}), 400
    set_clause = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [job_id]
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(f"UPDATE jobs SET {set_clause} WHERE id=?", values)
    log_action(user_id, f"JOB_UPDATED: id={job_id}")
    return jsonify({"status": "success", "message": "Job updated"})

@bp.route('/<int:job_id>', methods=['DELETE'])
@require_auth
@require_recruiter
def delete_job(user_id, job_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        job = conn.execute(
            "SELECT j.*, c.owner_email FROM jobs j JOIN companies c ON j.company_id=c.id WHERE j.id=?",
            (job_id,)
        ).fetchone()
    if not job:
        return jsonify({"status": "error", "message": "Job not found"}), 404
    if job['owner_email'] != user_id:
        return jsonify({"status": "error", "message": "Permission denied"}), 403
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("DELETE FROM applications WHERE job_id=?", (job_id,))
        conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    log_action(user_id, f"JOB_DELETED: id={job_id}")
    return jsonify({"status": "success", "message": "Job deleted"})
