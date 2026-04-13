import sqlite3
import hashlib
import pyotp
from datetime import datetime, timedelta, timezone
from flask import Blueprint, jsonify, request
from core.db import DB_NAME, require_auth, require_admin, log_action, finalize_audit_blocks, _build_merkle_root, _compute_block_hash, AUDIT_BLOCK_DIFFICULTY_PREFIX
import secureResumeUpload as resume

bp = Blueprint('admin', __name__)

@bp.route('/dashboard', methods=['GET'])
@require_auth
@require_admin
def admin_dashboard(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        users = conn.execute("SELECT id, email, name, role, is_verified, failed_attempts, locked_until, mfa_enabled FROM users ORDER BY id").fetchall()
        audit = conn.execute("SELECT id, email, ip_address, event, timestamp, prev_hash, log_hash FROM audit_logs ORDER BY id DESC LIMIT 100").fetchall()
        blocks = conn.execute("SELECT id, start_log_id, end_log_id, entry_count, merkle_root, prev_block_hash, nonce, authority, block_hash, created_at FROM log_blocks ORDER BY id DESC LIMIT 20").fetchall()
        resumes_data = conn.execute("SELECT r.resume_id, r.owner_user_id, r.upload_timestamp, r.file_size, r.original_ext, r.visibility, u.name as owner_name FROM resumes r LEFT JOIN users u ON r.owner_user_id = u.email ORDER BY r.upload_timestamp DESC").fetchall()
        active_sessions = conn.execute("SELECT s.user_id, s.role, s.created_at, s.expires_at FROM sessions s ORDER BY s.created_at DESC").fetchall()
        companies = conn.execute("SELECT c.*, u.name as owner_name, (SELECT COUNT(*) FROM jobs j WHERE j.company_id=c.id) as total_jobs FROM companies c LEFT JOIN users u ON c.owner_email=u.email ORDER BY c.created_at DESC").fetchall()
        jobs = conn.execute("SELECT j.*, c.name as company_name FROM jobs j JOIN companies c ON j.company_id=c.id ORDER BY j.created_at DESC").fetchall()
        applications = conn.execute(
            """SELECT a.*, j.title as job_title, c.name as company_name, u.name as applicant_name 
               FROM applications a 
               JOIN jobs j ON a.job_id=j.id 
               JOIN companies c ON j.company_id=c.id 
               LEFT JOIN users u ON a.applicant_email=u.email 
               ORDER BY a.applied_at DESC"""
        ).fetchall()
    return jsonify({
        "status": "success",
        "users": [dict(u) for u in users],
        "audit_logs": [dict(a) for a in audit],
        "audit_blocks": [dict(b) for b in blocks],
        "resumes": [dict(r) for r in resumes_data],
        "active_sessions": [dict(s) for s in active_sessions],
        "companies": [dict(c) for c in companies],
        "jobs": [dict(j) for j in jobs],
        "applications": [dict(a) for a in applications]
    })


@bp.route('/users/<int:target_user_id>/suspend', methods=['PUT'])
@require_auth
@require_admin
def suspend_user(user_id, target_user_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        target = conn.execute("SELECT id, email, role, locked_until FROM users WHERE id=?", (target_user_id,)).fetchone()
        if not target:
            return jsonify({"status": "error", "message": "User not found"}), 404
        if target['email'] == user_id:
            return jsonify({"status": "error", "message": "Admins cannot suspend themselves"}), 400

        locked_until = (datetime.now(timezone.utc) + timedelta(days=36500)).isoformat()
        conn.execute("UPDATE users SET locked_until=? WHERE id=?", (locked_until, target_user_id))
        conn.commit()

    log_action(user_id, f"ADMIN_USER_SUSPENDED: target={target['email']}")
    return jsonify({
        "status": "success",
        "message": f"User {target['email']} suspended",
        "locked_until": locked_until
    })


@bp.route('/users/<int:target_user_id>/unsuspend', methods=['PUT'])
@require_auth
@require_admin
def unsuspend_user(user_id, target_user_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        target = conn.execute("SELECT id, email FROM users WHERE id=?", (target_user_id,)).fetchone()
        if not target:
            return jsonify({"status": "error", "message": "User not found"}), 404

        conn.execute("UPDATE users SET locked_until=NULL, failed_attempts=0 WHERE id=?", (target_user_id,))
        conn.commit()

    log_action(user_id, f"ADMIN_USER_UNSUSPENDED: target={target['email']}")
    return jsonify({"status": "success", "message": f"User {target['email']} unsuspended"})


@bp.route('/users/<int:target_user_id>', methods=['DELETE'])
@require_auth
@require_admin
def delete_user(user_id, target_user_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        target = conn.execute("SELECT id, email, role FROM users WHERE id=?", (target_user_id,)).fetchone()
        if not target:
            return jsonify({"status": "error", "message": "User not found"}), 404
        if target['email'] == user_id:
            return jsonify({"status": "error", "message": "Admins cannot delete themselves"}), 400

        resumes_to_delete = conn.execute(
            "SELECT resume_id, encrypted_file_ref FROM resumes WHERE owner_user_id=?",
            (target['email'],)
        ).fetchall()
        owned_company_ids = [
            row['id'] for row in conn.execute(
                "SELECT id FROM companies WHERE owner_email=?",
                (target['email'],)
            ).fetchall()
        ]

        for resume_row in resumes_to_delete:
            file_ref = resume_row['encrypted_file_ref']
            resume._overwrite_and_remove(resume.STORAGE_DIR / file_ref)
            resume._overwrite_and_remove(resume.KEYS_DIR / (file_ref + '.key'))

        if owned_company_ids:
            placeholders = ','.join('?' * len(owned_company_ids))
            job_ids = [
                row['id'] for row in conn.execute(
                    f"SELECT id FROM jobs WHERE company_id IN ({placeholders})",
                    owned_company_ids
                ).fetchall()
            ]
            if job_ids:
                job_placeholders = ','.join('?' * len(job_ids))
                conn.execute(f"DELETE FROM applications WHERE job_id IN ({job_placeholders})", job_ids)
                conn.execute(f"DELETE FROM jobs WHERE id IN ({job_placeholders})", job_ids)
            conn.execute(f"DELETE FROM companies WHERE id IN ({placeholders})", owned_company_ids)

        conn.execute("DELETE FROM resumes WHERE owner_user_id=?", (target['email'],))
        conn.execute("DELETE FROM sessions WHERE user_id=?", (target['email'],))
        conn.execute("DELETE FROM applications WHERE applicant_email=?", (target['email'],))
        conn.execute("DELETE FROM conversation_members WHERE user_email=?", (target['email'],))
        conn.execute("DELETE FROM messages WHERE sender_email=?", (target['email'],))
        conn.execute("DELETE FROM connections WHERE requester_email=? OR recipient_email=?", (target['email'], target['email']))
        conn.execute("DELETE FROM profile_views WHERE viewer_email=? OR viewed_email=?", (target['email'], target['email']))
        conn.execute("DELETE FROM verification_tokens WHERE email=?", (target['email'],))
        conn.execute("DELETE FROM mfa_pending_sessions WHERE email=?", (target['email'],))
        conn.execute("DELETE FROM conversations WHERE id NOT IN (SELECT conversation_id FROM conversation_members)")
        conn.execute("DELETE FROM users WHERE id=?", (target_user_id,))
        conn.commit()

    log_action(user_id, f"ADMIN_USER_DELETED: target={target['email']}")
    return jsonify({"status": "success", "message": f"User {target['email']} deleted"})


@bp.route('/audit/verify', methods=['GET'])
@require_auth
@require_admin
def verify_audit_chain(user_id):
    """Verify both the per-entry hash chain and the higher-level audit block chain."""
    finalize_audit_blocks(force=True)
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        logs = conn.execute("SELECT id, email, ip_address, event, timestamp, prev_hash, log_hash FROM audit_logs ORDER BY id ASC").fetchall()
        blocks = conn.execute("SELECT * FROM log_blocks ORDER BY id ASC").fetchall()

    if not logs:
        return jsonify({
            "status": "success",
            "chain_valid": True,
            "total_entries": 0,
            "message": "No audit log entries to verify"
        })

    broken_links = []
    total = len(logs)

    for i, log in enumerate(logs):
        # Determine expected prev_hash
        if i == 0:
            expected_prev = 'GENESIS'
        else:
            expected_prev = logs[i - 1]['log_hash']

        # Check prev_hash matches
        actual_prev = log['prev_hash'] if log['prev_hash'] else ''
        if actual_prev != expected_prev:
            broken_links.append({
                "log_id": log['id'],
                "position": i + 1,
                "error": "prev_hash mismatch",
                "expected_prev_hash": expected_prev[:16] + "...",
                "actual_prev_hash": actual_prev[:16] + "..." if actual_prev else "(empty)"
            })
            continue

        # Recompute hash and verify
        chain_input = f"{log['prev_hash']}|{log['email']}|{log['event']}|{log['timestamp']}|{log['ip_address']}"
        expected_hash = hashlib.sha256(chain_input.encode('utf-8')).hexdigest()
        if log['log_hash'] != expected_hash:
            broken_links.append({
                "log_id": log['id'],
                "position": i + 1,
                "error": "log_hash does not match recomputed hash",
                "expected_hash": expected_hash[:16] + "...",
                "actual_hash": log['log_hash'][:16] + "..." if log['log_hash'] else "(empty)"
            })

    chain_valid = len(broken_links) == 0

    broken_blocks = []
    for i, block in enumerate(blocks):
        expected_prev_block = 'GENESIS' if i == 0 else blocks[i - 1]['block_hash']
        if block['prev_block_hash'] != expected_prev_block:
            broken_blocks.append({
                "block_id": block['id'],
                "error": "prev_block_hash mismatch",
                "expected_prev_block_hash": expected_prev_block[:16] + "...",
                "actual_prev_block_hash": (block['prev_block_hash'] or '')[:16] + "..."
            })
            continue

        block_logs = [log for log in logs if block['start_log_id'] <= log['id'] <= block['end_log_id']]
        if len(block_logs) != block['entry_count']:
            broken_blocks.append({
                "block_id": block['id'],
                "error": "entry_count mismatch",
                "expected_entry_count": block['entry_count'],
                "actual_entry_count": len(block_logs)
            })
            continue

        merkle_root = _build_merkle_root([log['log_hash'] for log in block_logs])
        if merkle_root != block['merkle_root']:
            broken_blocks.append({
                "block_id": block['id'],
                "error": "merkle_root mismatch",
                "expected_merkle_root": merkle_root[:16] + "...",
                "actual_merkle_root": (block['merkle_root'] or '')[:16] + "..."
            })
            continue

        expected_hash = _compute_block_hash(
            block['prev_block_hash'],
            block['start_log_id'],
            block['end_log_id'],
            block['entry_count'],
            block['merkle_root'],
            block['created_at'],
            block['nonce']
        )
        if expected_hash != block['block_hash'] or not expected_hash.startswith(AUDIT_BLOCK_DIFFICULTY_PREFIX):
            broken_blocks.append({
                "block_id": block['id'],
                "error": "block_hash or nonce mismatch",
                "expected_block_hash": expected_hash[:16] + "...",
                "actual_block_hash": (block['block_hash'] or '')[:16] + "...",
                "actual_nonce": block['nonce']
            })

    blockchain_valid = len(broken_blocks) == 0
    log_action(
        user_id,
        f"AUDIT_CHAIN_VERIFIED: valid={chain_valid}, entries={total}, breaks={len(broken_links)}, blockchain_valid={blockchain_valid}, blocks={len(blocks)}"
    )

    return jsonify({
        "status": "success",
        "chain_valid": chain_valid,
        "blockchain_valid": blockchain_valid,
        "total_entries": total,
        "total_blocks": len(blocks),
        "broken_links": broken_links,
        "broken_blocks": broken_blocks,
        "blocks": [dict(b) for b in blocks],
        "message": "Audit chain and blockchain verified — no tampering detected"
        if chain_valid and blockchain_valid
        else f"Integrity issues found: {len(broken_links)} log breaks, {len(broken_blocks)} block breaks"
    })


@bp.route('/otp/verify', methods=['POST'])
@require_auth
def verify_otp_for_action(user_id):
    """
    Verify a TOTP code for high-risk action authorization.
    This endpoint is used by the virtual keyboard widget before allowing
    sensitive operations (resume download, password change, etc.).
    """
    data = request.json
    totp_code = data.get('totp_code', '').strip()
    action = data.get('action', 'unknown')

    if not totp_code or len(totp_code) != 6:
        return jsonify({"status": "error", "message": "A 6-digit OTP code is required"}), 400

    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        user = conn.execute("SELECT mfa_secret, mfa_enabled FROM users WHERE email=?", (user_id,)).fetchone()

    if not user or not user['mfa_enabled']:
        return jsonify({"status": "error", "message": "MFA is not enabled for this account"}), 400

    # Decrypt the MFA secret (it's stored Fernet-encrypted)
    try:
        from auth_secTOTP import _decrypt_mfa_secret
        secret = _decrypt_mfa_secret(user['mfa_secret'])
    except Exception:
        # Fallback: try using it directly if not encrypted
        secret = user['mfa_secret']

    totp = pyotp.TOTP(secret)
    if not totp.verify(totp_code, valid_window=1):
        log_action(user_id, f"OTP_VERIFICATION_FAILED: action={action}")
        return jsonify({"status": "error", "message": "Invalid OTP code"}), 401

    log_action(user_id, f"OTP_VERIFICATION_SUCCESS: action={action}")
    return jsonify({"status": "success", "message": "OTP verified", "action": action})
