import sqlite3
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from core.db import DB_NAME, require_auth, require_recruiter, log_action
import resume_matching
import secureResumeUpload as resume

bp = Blueprint('applications', __name__)

@bp.route('', methods=['POST'])
@require_auth
def apply_for_job(user_id):
    data = request.json
    job_id = data.get('job_id')
    resume_id = data.get('resume_id', '')
    cover_note = data.get('cover_note', '').strip()
    if not job_id:
        return jsonify({"status": "error", "message": "job_id is required"}), 400
    # Verify job exists and is active
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        job = conn.execute("SELECT * FROM jobs WHERE id=? AND status='active'", (job_id,)).fetchone()
    if not job:
        return jsonify({"status": "error", "message": "Job not found or no longer active"}), 404
    # Verify resume belongs to applicant (if provided)
    if resume_id:
        with sqlite3.connect(DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            res = conn.execute("SELECT * FROM resumes WHERE resume_id=? AND owner_user_id=?", (resume_id, user_id)).fetchone()
        if not res:
            return jsonify({"status": "error", "message": "Resume not found or not yours"}), 403
    # Check for duplicate application
    now = datetime.now(timezone.utc).isoformat()
    try:
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute(
                "INSERT INTO applications (job_id, applicant_email, resume_id, cover_note, status, applied_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (job_id, user_id, resume_id, cover_note, 'Applied', now, now)
            )
    except sqlite3.IntegrityError:
        return jsonify({"status": "error", "message": "You have already applied to this job"}), 409
    log_action(user_id, f"APPLICATION_SUBMITTED: job_id={job_id}")
    return jsonify({"status": "success", "message": "Application submitted"})

@bp.route('/me', methods=['GET'])
@require_auth
def my_applications(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        apps = conn.execute(
            """SELECT a.*, j.title as job_title, c.name as company_name
               FROM applications a
               JOIN jobs j ON a.job_id=j.id
               JOIN companies c ON j.company_id=c.id
               WHERE a.applicant_email=?
               ORDER BY a.applied_at DESC""",
            (user_id,)
        ).fetchall()
    return jsonify({"status": "success", "applications": [dict(a) for a in apps]})

@bp.route('/job/<int:job_id>', methods=['GET'])
@require_auth
@require_recruiter
def job_applicants(user_id, job_id):
    # Verify recruiter owns the company that posted this job
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
        conn.row_factory = sqlite3.Row
        applicants = conn.execute(
            """SELECT a.*, u.name as applicant_name, u.headline as applicant_headline,
                      r.parsed_text as resume_parsed_text, r.parsed_skills as resume_parsed_skills
               FROM applications a
               JOIN users u ON a.applicant_email=u.email
               LEFT JOIN resumes r ON a.resume_id=r.resume_id
               WHERE a.job_id=?
               ORDER BY a.applied_at DESC""",
            (job_id,)
        ).fetchall()

    applicant_payload = []
    for applicant in applicants:
        row = dict(applicant)
        resume_text = row.get('resume_parsed_text') or ''
        resume_skills = [s for s in (row.get('resume_parsed_skills') or '').split(',') if s]

        if row.get('resume_id') and not resume_text:
            record = resume._fetch_resume_record(row['resume_id'])
            if record:
                try:
                    encrypted_blob = resume._load_encrypted_blob(record['encrypted_file_ref'])
                    key_bytes = resume._load_key_bytes(record['encrypted_file_ref'])
                    plaintext = resume.decrypt_in_memory(encrypted_blob, key_bytes)
                    filename = f"resume_{row['resume_id']}{record.get('original_ext', '.pdf')}"
                    resume_text = resume_matching.extract_resume_text(plaintext, filename)
                    resume_skills = resume_matching.extract_skills_from_text(resume_text)
                    with sqlite3.connect(DB_NAME) as update_conn:
                        update_conn.execute(
                            "UPDATE resumes SET parsed_text=?, parsed_skills=? WHERE resume_id=?",
                            (resume_text, ",".join(resume_skills), row['resume_id'])
                        )
                        update_conn.commit()
                except Exception:
                    resume_text = ''
                    resume_skills = []

        match = resume_matching.compute_job_match(
            job['title'],
            job['description'],
            job['skills'],
            resume_text,
            resume_skills
        )
        row['resume_match_score'] = match['score']
        row['matched_skills'] = match['matched_skills']
        row['missing_skills'] = match['missing_skills']
        row['requested_skills'] = match['requested_skills']
        row['resume_skills_detected'] = match['resume_skills_detected']
        row.pop('resume_parsed_text', None)
        row.pop('resume_parsed_skills', None)
        applicant_payload.append(row)

    return jsonify({"status": "success", "applicants": applicant_payload})

@bp.route('/<int:app_id>/status', methods=['PUT'])
@require_auth
@require_recruiter
def update_application_status(user_id, app_id):
    data = request.json
    new_status = data.get('status', '').strip()
    notes = data.get('recruiter_notes', '').strip()
    valid_statuses = {'Applied', 'Reviewed', 'Interviewed', 'Rejected', 'Offer'}
    if new_status not in valid_statuses:
        return jsonify({"status": "error", "message": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"}), 400
    # Verify recruiter owns the company
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        app_record = conn.execute(
            """SELECT a.*, j.company_id, c.owner_email
               FROM applications a
               JOIN jobs j ON a.job_id=j.id
               JOIN companies c ON j.company_id=c.id
               WHERE a.id=?""",
            (app_id,)
        ).fetchone()
    if not app_record:
        return jsonify({"status": "error", "message": "Application not found"}), 404
    if app_record['owner_email'] != user_id:
        return jsonify({"status": "error", "message": "Permission denied"}), 403
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_NAME) as conn:
        if notes:
            conn.execute("UPDATE applications SET status=?, recruiter_notes=?, updated_at=? WHERE id=?",
                         (new_status, notes, now, app_id))
        else:
            conn.execute("UPDATE applications SET status=?, updated_at=? WHERE id=?",
                         (new_status, now, app_id))
    log_action(user_id, f"APPLICATION_STATUS_CHANGED: app_id={app_id} -> {new_status}")
    return jsonify({"status": "success", "message": f"Application status updated to {new_status}"})
