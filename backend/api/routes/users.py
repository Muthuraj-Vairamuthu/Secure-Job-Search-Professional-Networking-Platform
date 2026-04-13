import os
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from flask import Blueprint, request, jsonify, make_response
from core.db import DB_NAME, get_client_ip, require_auth, log_action
import pki
import resume_matching

import credChange as cred
import secureResumeUpload as resume

# Ensure resume uses the right DB
resume.DB_PATH = Path(DB_NAME).resolve()
cred.setup_demo_db = lambda: None

bp = Blueprint('users', __name__)

@bp.route('/me', methods=['GET'])
@require_auth
def get_profile(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        user = conn.execute("SELECT email, name, role, bio, location, headline, skills, education, experience, profile_picture_url, privacy_profile, show_profile_views FROM users WHERE email=?", (user_id,)).fetchone()
    if not user:
        return jsonify({"status": "error", "message": "User not found"}), 404
    return jsonify({
        "status": "success",
        "email": user['email'],
        "name": user['name'] or user['email'].split('@')[0],
        "role": user['role'],
        "bio": user['bio'],
        "location": user['location'],
        "headline": user['headline'],
        "skills": _split_multiline_field(user['skills']),
        "education": _split_multiline_field(user['education']),
        "experience": _split_multiline_field(user['experience']),
        "profile_picture_url": user['profile_picture_url'],
        "privacy_profile": user['privacy_profile'] if 'privacy_profile' in user.keys() else 'public',
        "show_profile_views": bool(user['show_profile_views']) if 'show_profile_views' in user.keys() else True
    })

@bp.route('/me', methods=['PUT'])
@require_auth
def update_profile(user_id):
    data = request.json or {}
    allowed = {'name', 'bio', 'location', 'headline', 'profile_picture_url'}
    updates = {k: v.strip() if isinstance(v, str) else v for k, v in data.items() if k in allowed and isinstance(v, str)}

    multiline_fields = ('skills', 'education', 'experience')
    for field in multiline_fields:
        if field in data:
            value = data[field]
            if isinstance(value, list):
                cleaned = [str(item).strip() for item in value if str(item).strip()]
                updates[field] = "\n".join(cleaned)
            elif isinstance(value, str):
                updates[field] = "\n".join(line.strip() for line in value.splitlines() if line.strip())

    if not updates:
        return jsonify({"status": "error", "message": "No valid fields to update"}), 400
    set_clause = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [user_id]
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(f"UPDATE users SET {set_clause} WHERE email=?", values)
        conn.commit()
    return jsonify({"status": "success", "message": "Profile updated"})


@bp.route('/me/privacy', methods=['GET'])
@require_auth
def get_privacy(user_id):
    """Get privacy settings for the current user."""
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        user = conn.execute("SELECT privacy_profile, show_profile_views FROM users WHERE email=?", (user_id,)).fetchone()
    if not user:
        return jsonify({"status": "error", "message": "User not found"}), 404
    return jsonify({
        "status": "success",
        "privacy_profile": user['privacy_profile'],
        "show_profile_views": bool(user['show_profile_views'])
    })


@bp.route('/me/privacy', methods=['PUT'])
@require_auth
def update_privacy(user_id):
    """Update privacy settings."""
    data = request.json
    updates = {}
    if 'privacy_profile' in data and data['privacy_profile'] in ('public', 'connections', 'private'):
        updates['privacy_profile'] = data['privacy_profile']
    if 'show_profile_views' in data and isinstance(data['show_profile_views'], bool):
        updates['show_profile_views'] = 1 if data['show_profile_views'] else 0
    if not updates:
        return jsonify({"status": "error", "message": "No valid privacy settings provided"}), 400
    set_clause = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [user_id]
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(f"UPDATE users SET {set_clause} WHERE email=?", values)
        conn.commit()
    log_action(user_id, "PRIVACY_SETTINGS_UPDATED")
    return jsonify({"status": "success", "message": "Privacy settings updated"})


@bp.route('/me/views', methods=['GET'])
@require_auth
def get_profile_views(user_id):
    """Get profile view count and recent viewers."""
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        # Views in the last 7 days
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        count = conn.execute(
            "SELECT COUNT(*) as cnt FROM profile_views WHERE viewed_email=? AND timestamp > ?",
            (user_id, week_ago)
        ).fetchone()['cnt']

        # Recent viewers (only those who allow showing views)
        viewers = conn.execute("""
            SELECT pv.viewer_email, u.name, u.headline, MAX(pv.timestamp) as last_viewed
            FROM profile_views pv
            JOIN users u ON u.email = pv.viewer_email
            WHERE pv.viewed_email = ? AND pv.timestamp > ? AND u.show_profile_views = 1
            GROUP BY pv.viewer_email
            ORDER BY last_viewed DESC
            LIMIT 10
        """, (user_id, week_ago)).fetchall()

    return jsonify({
        "status": "success",
        "views_this_week": count,
        "recent_viewers": [dict(v) for v in viewers]
    })


@bp.route('/profile/<email>', methods=['GET'])
@require_auth
def view_user_profile(user_id, email):
    """View another user's profile (respects privacy settings)."""
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        user = conn.execute(
            "SELECT email, name, role, bio, location, headline, skills, education, experience, profile_picture_url, privacy_profile FROM users WHERE email=?",
            (email,)
        ).fetchone()
        if not user:
            return jsonify({"status": "error", "message": "User not found"}), 404

        # Track view (don't track self-views)
        if email != user_id:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO profile_views (viewer_email, viewed_email, timestamp) VALUES (?, ?, ?)",
                (user_id, email, now)
            )
            conn.commit()

        privacy = user['privacy_profile']
        is_self = (email == user_id)

        # Check connection status
        is_connected = False
        if not is_self:
            conn_row = conn.execute("""
                SELECT status FROM connections
                WHERE ((requester_email=? AND recipient_email=?) OR (requester_email=? AND recipient_email=?))
                  AND status='accepted'
            """, (user_id, email, email, user_id)).fetchone()
            is_connected = conn_row is not None

        # Build profile based on privacy
        profile = {"status": "success", "email": user['email'], "name": user['name'] or user['email'].split('@')[0], "role": user['role']}

        if is_self or privacy == 'public' or (privacy == 'connections' and is_connected):
            profile["bio"] = user['bio']
            profile["location"] = user['location']
            profile["headline"] = user['headline']
            profile["skills"] = _split_multiline_field(user['skills'])
            profile["education"] = _split_multiline_field(user['education'])
            profile["experience"] = _split_multiline_field(user['experience'])
            profile["profile_picture_url"] = user['profile_picture_url']
            profile["full_access"] = True
        else:
            profile["full_access"] = False
            profile["privacy_restricted"] = True

        profile["is_connected"] = is_connected

    return jsonify(profile)

@bp.route('/me/password', methods=['PUT'])
@require_auth
def change_password(user_id):
    data = request.json
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    totp_code = data.get('totp_code')
    ip = get_client_ip()
    res = cred.change_password(user_id, current_password, totp_code, new_password, ip)
    return jsonify(res)

@bp.route('/resumes', methods=['POST'])
@require_auth
def upload_resume(user_id):
    if 'resume' not in request.files:
        return jsonify({"status": "error", "message": "No file part"}), 400
    file = request.files['resume']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No selected file"}), 400
    file_bytes = file.read()
    filename = file.filename

    valid, reason = resume.validate_file(filename, file_bytes)
    if not valid:
        return jsonify({"status": "error", "message": reason}), 400

    scan_ok, scan_result = resume.security_scan(file_bytes, filename)
    if not scan_ok:
        return jsonify({"status": "error", "message": scan_result}), 400
    clean_bytes, safe_name = scan_result

    original_size = len(clean_bytes)
    plaintext_hash = resume.compute_file_hash(clean_bytes)
    _, ext = os.path.splitext(safe_name)
    parsed_text = resume_matching.extract_resume_text(clean_bytes, safe_name)
    parsed_skills = resume_matching.extract_skills_from_text(parsed_text)

    encrypted_blob, key_bytes, rand_filename = resume.encrypt_file(clean_bytes, user_id)
    resume_id = resume.store_encrypted_file(
        encrypted_blob, key_bytes, rand_filename,
        user_id, plaintext_hash, ext, original_size, "private",
    )

    # PKI: Sign the plaintext hash with the user's RSA private key
    private_pem, public_pem = pki.get_or_create_keypair(DB_NAME, user_id)
    signature = pki.sign_data(private_pem, plaintext_hash.encode('utf-8'))
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("UPDATE resumes SET digital_signature=? WHERE resume_id=?", (signature, resume_id))
        conn.execute(
            "UPDATE resumes SET parsed_text=?, parsed_skills=? WHERE resume_id=?",
            (parsed_text, ",".join(parsed_skills), resume_id)
        )
        conn.commit()

    resume.log_event("UPLOAD_SUCCESS", user_id, {"resume_id": resume_id, "safe_name": safe_name, "size_bytes": original_size, "pki_signed": True})
    log_action(user_id, f"RESUME_UPLOADED_AND_SIGNED: {resume_id}")
    return jsonify({
        "status": "success",
        "resume_id": resume_id,
        "pki_signed": True,
        "parsed_skills": parsed_skills
    })

@bp.route('/resumes', methods=['GET'])
@require_auth
def list_resumes(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT resume_id, upload_timestamp, file_size, original_ext, visibility, digital_signature, parsed_skills FROM resumes WHERE owner_user_id=? ORDER BY upload_timestamp DESC",
            (user_id,)
        ).fetchall()
    resumes = []
    for r in rows:
        d = dict(r)
        d['is_signed'] = bool(d.get('digital_signature'))
        d['parsed_skills'] = [s for s in (d.get('parsed_skills') or '').split(',') if s]
        resumes.append(d)
    return jsonify({"status": "success", "resumes": resumes})

@bp.route('/resumes/<resume_id>/download', methods=['GET'])
@require_auth
def download_resume(user_id, resume_id):
    record = resume._fetch_resume_record(resume_id)
    if not record:
        return jsonify({"status": "error", "message": "Resume not found"}), 404
    if not _can_access_resume(user_id, resume_id, record['owner_user_id']):
        return jsonify({"status": "error", "message": "Permission denied"}), 403
    file_ref = record['encrypted_file_ref']
    try:
        encrypted_blob = resume._load_encrypted_blob(file_ref)
        key_bytes = resume._load_key_bytes(file_ref)
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "File not found on disk"}), 404
    if not resume.verify_integrity(encrypted_blob, record):
        return jsonify({"status": "error", "message": "Integrity check failed"}), 500
    plaintext = resume.decrypt_in_memory(encrypted_blob, key_bytes)

    # PKI: Verify the digital signature if present
    sig_status = "unsigned"
    if record.get('digital_signature'):
        owner_pub_key = pki.get_public_key(DB_NAME, record['owner_user_id'])
        if owner_pub_key:
            verified, sig_msg = pki.verify_signature(
                owner_pub_key,
                record['file_hash'].encode('utf-8'),
                record['digital_signature']
            )
            sig_status = "valid" if verified else "invalid"
        else:
            sig_status = "no_public_key"

    ext = record.get('original_ext', '.pdf')
    resp_data = resume.serve_resume(plaintext, f"resume_{resume_id}{ext}")
    resp = make_response(resp_data['body'])
    for k, v in resp_data['headers'].items():
        resp.headers[k] = v
    resp.headers['X-PKI-Signature-Status'] = sig_status
    resp.headers['X-PKI-Signer'] = record['owner_user_id']
    return resp

@bp.route('/resumes/<resume_id>', methods=['DELETE'])
@require_auth
def delete_resume(user_id, resume_id):
    record = resume._fetch_resume_record(resume_id)
    if not record:
        return jsonify({"status": "error", "message": "Resume not found"}), 404
    if record['owner_user_id'] != user_id:
        return jsonify({"status": "error", "message": "Permission denied"}), 403
    file_ref = record['encrypted_file_ref']
    resume._overwrite_and_remove(resume.STORAGE_DIR / file_ref)
    resume._overwrite_and_remove(resume.KEYS_DIR / (file_ref + '.key'))
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("DELETE FROM resumes WHERE resume_id=?", (resume_id,))
    resume.log_event("RESUME_DELETED", user_id, {"resume_id": resume_id})
    return jsonify({"status": "success", "message": "Resume deleted"})


@bp.route('/resumes/<resume_id>/verify', methods=['GET'])
@require_auth
def verify_resume_signature(user_id, resume_id):
    """Verify the digital signature of a resume (PKI Function 1)."""
    record = resume._fetch_resume_record(resume_id)
    if not record:
        return jsonify({"status": "error", "message": "Resume not found"}), 404

    sig = record.get('digital_signature', '')
    if not sig:
        return jsonify({
            "status": "success",
            "verified": False,
            "reason": "Resume has no digital signature",
            "signer": record['owner_user_id']
        })

    owner_pub_key = pki.get_public_key(DB_NAME, record['owner_user_id'])
    if not owner_pub_key:
        return jsonify({
            "status": "success",
            "verified": False,
            "reason": "Signer's public key not found",
            "signer": record['owner_user_id']
        })

    verified, msg = pki.verify_signature(
        owner_pub_key,
        record['file_hash'].encode('utf-8'),
        sig
    )
    return jsonify({
        "status": "success",
        "verified": verified,
        "reason": msg,
        "signer": record['owner_user_id'],
        "signature_algorithm": "RSA-2048-PSS-SHA256"
    })


@bp.route('/me/pki', methods=['GET'])
@require_auth
def get_pki_info(user_id):
    """Get the current user's PKI public key (or generate one)."""
    _, public_pem = pki.get_or_create_keypair(DB_NAME, user_id)
    return jsonify({
        "status": "success",
        "email": user_id,
        "public_key": public_pem,
        "algorithm": "RSA-2048"
    })


def _split_multiline_field(value):
    return [line.strip() for line in (value or '').splitlines() if line.strip()]


def _can_access_resume(requester_email, resume_id, owner_email):
    if requester_email == owner_email:
        return True

    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        requester = conn.execute("SELECT role FROM users WHERE email=?", (requester_email,)).fetchone()
        if requester and requester['role'] == 'admin':
            return True

        if requester and requester['role'] == 'recruiter':
            authorized = conn.execute(
                """SELECT 1
                   FROM applications a
                   JOIN jobs j ON a.job_id = j.id
                   JOIN companies c ON j.company_id = c.id
                   WHERE a.resume_id=? AND c.owner_email=?
                   LIMIT 1""",
                (resume_id, requester_email)
            ).fetchone()
            return authorized is not None

    return False
