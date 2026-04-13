import sqlite3
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from core.db import DB_NAME, require_auth, log_action

bp = Blueprint('connections', __name__)


@bp.route('', methods=['GET'])
@require_auth
def list_connections(user_id):
    """List all connections for the current user (accepted, pending sent, pending received)."""
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row

        # Accepted connections
        accepted = conn.execute("""
            SELECT c.id, c.requester_email, c.recipient_email, c.status, c.created_at,
                   u.name, u.headline, u.location, u.role
            FROM connections c
            JOIN users u ON u.email = CASE WHEN c.requester_email = ? THEN c.recipient_email ELSE c.requester_email END
            WHERE (c.requester_email = ? OR c.recipient_email = ?) AND c.status = 'accepted'
            ORDER BY c.updated_at DESC
        """, (user_id, user_id, user_id)).fetchall()

        # Pending received (invitations to me)
        pending_received = conn.execute("""
            SELECT c.id, c.requester_email, c.status, c.created_at,
                   u.name, u.headline, u.role
            FROM connections c
            JOIN users u ON u.email = c.requester_email
            WHERE c.recipient_email = ? AND c.status = 'pending'
            ORDER BY c.created_at DESC
        """, (user_id,)).fetchall()

        # Pending sent (my outgoing requests)
        pending_sent = conn.execute("""
            SELECT c.id, c.recipient_email, c.status, c.created_at,
                   u.name, u.headline, u.role
            FROM connections c
            JOIN users u ON u.email = c.recipient_email
            WHERE c.requester_email = ? AND c.status = 'pending'
            ORDER BY c.created_at DESC
        """, (user_id,)).fetchall()

    return jsonify({
        "status": "success",
        "connections": [dict(r) for r in accepted],
        "pending_received": [dict(r) for r in pending_received],
        "pending_sent": [dict(r) for r in pending_sent],
        "total_connections": len(accepted)
    })


@bp.route('/request', methods=['POST'])
@require_auth
def send_request(user_id):
    """Send a connection request to another user."""
    data = request.json
    target_email = data.get('email', '').strip()

    if not target_email:
        return jsonify({"status": "error", "message": "Email is required"}), 400
    if target_email == user_id:
        return jsonify({"status": "error", "message": "Cannot connect to yourself"}), 400

    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row

        # Check target user exists
        target = conn.execute("SELECT email FROM users WHERE email=?", (target_email,)).fetchone()
        if not target:
            return jsonify({"status": "error", "message": "User not found"}), 404

        # Check if connection already exists in either direction
        existing = conn.execute("""
            SELECT id, status FROM connections
            WHERE (requester_email=? AND recipient_email=?) OR (requester_email=? AND recipient_email=?)
        """, (user_id, target_email, target_email, user_id)).fetchone()

        if existing:
            if existing['status'] == 'accepted':
                return jsonify({"status": "error", "message": "Already connected"}), 409
            elif existing['status'] == 'pending':
                return jsonify({"status": "error", "message": "Connection request already pending"}), 409
            elif existing['status'] == 'rejected':
                # Allow re-requesting after a rejection
                now = datetime.now(timezone.utc).isoformat()
                conn.execute("UPDATE connections SET status='pending', requester_email=?, recipient_email=?, updated_at=? WHERE id=?",
                             (user_id, target_email, now, existing['id']))
                conn.commit()
                log_action(user_id, f"CONNECTION_REQUEST_RESENT to {target_email}")
                return jsonify({"status": "success", "message": "Connection request sent", "connection_id": existing['id']})

        now = datetime.now(timezone.utc).isoformat()
        cursor = conn.execute(
            "INSERT INTO connections (requester_email, recipient_email, status, created_at, updated_at) VALUES (?, ?, 'pending', ?, ?)",
            (user_id, target_email, now, now)
        )
        conn.commit()
        log_action(user_id, f"CONNECTION_REQUEST_SENT to {target_email}")

    return jsonify({"status": "success", "message": "Connection request sent", "connection_id": cursor.lastrowid}), 201


@bp.route('/<int:conn_id>/accept', methods=['PUT'])
@require_auth
def accept_request(user_id, conn_id):
    """Accept a pending connection request."""
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM connections WHERE id=?", (conn_id,)).fetchone()

        if not row:
            return jsonify({"status": "error", "message": "Connection not found"}), 404
        if row['recipient_email'] != user_id:
            return jsonify({"status": "error", "message": "Only the recipient can accept"}), 403
        if row['status'] != 'pending':
            return jsonify({"status": "error", "message": f"Cannot accept a {row['status']} connection"}), 400

        now = datetime.now(timezone.utc).isoformat()
        conn.execute("UPDATE connections SET status='accepted', updated_at=? WHERE id=?", (now, conn_id))
        conn.commit()
        log_action(user_id, f"CONNECTION_ACCEPTED from {row['requester_email']}")

    return jsonify({"status": "success", "message": "Connection accepted"})


@bp.route('/<int:conn_id>/reject', methods=['PUT'])
@require_auth
def reject_request(user_id, conn_id):
    """Reject a pending connection request."""
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM connections WHERE id=?", (conn_id,)).fetchone()

        if not row:
            return jsonify({"status": "error", "message": "Connection not found"}), 404
        if row['recipient_email'] != user_id:
            return jsonify({"status": "error", "message": "Only the recipient can reject"}), 403
        if row['status'] != 'pending':
            return jsonify({"status": "error", "message": f"Cannot reject a {row['status']} connection"}), 400

        now = datetime.now(timezone.utc).isoformat()
        conn.execute("UPDATE connections SET status='rejected', updated_at=? WHERE id=?", (now, conn_id))
        conn.commit()
        log_action(user_id, f"CONNECTION_REJECTED from {row['requester_email']}")

    return jsonify({"status": "success", "message": "Connection rejected"})


@bp.route('/<int:conn_id>', methods=['DELETE'])
@require_auth
def remove_connection(user_id, conn_id):
    """Remove/cancel a connection (works for both requester and recipient)."""
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM connections WHERE id=?", (conn_id,)).fetchone()

        if not row:
            return jsonify({"status": "error", "message": "Connection not found"}), 404
        if row['requester_email'] != user_id and row['recipient_email'] != user_id:
            return jsonify({"status": "error", "message": "Permission denied"}), 403

        other = row['recipient_email'] if row['requester_email'] == user_id else row['requester_email']
        conn.execute("DELETE FROM connections WHERE id=?", (conn_id,))
        conn.commit()
        log_action(user_id, f"CONNECTION_REMOVED with {other}")

    return jsonify({"status": "success", "message": "Connection removed"})


@bp.route('/graph', methods=['GET'])
@require_auth
def connection_graph(user_id):
    """Get 1st and 2nd degree connections for graph visualization."""
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row

        # 1st degree: direct connections
        first_degree = conn.execute("""
            SELECT u.email, u.name, u.headline
            FROM connections c
            JOIN users u ON u.email = CASE WHEN c.requester_email = ? THEN c.recipient_email ELSE c.requester_email END
            WHERE (c.requester_email = ? OR c.recipient_email = ?) AND c.status = 'accepted'
        """, (user_id, user_id, user_id)).fetchall()

        first_emails = [r['email'] for r in first_degree]
        nodes = [{"email": user_id, "name": "You", "degree": 0}]
        edges = []

        for r in first_degree:
            nodes.append({"email": r['email'], "name": r['name'] or r['email'], "headline": r['headline'] or '', "degree": 1})
            edges.append({"from": user_id, "to": r['email']})

        # 2nd degree: connections of connections (excluding self and 1st degree)
        if first_emails:
            placeholders = ','.join('?' * len(first_emails))
            second_degree = conn.execute(f"""
                SELECT DISTINCT u.email, u.name, u.headline,
                       CASE WHEN c.requester_email IN ({placeholders}) THEN c.requester_email ELSE c.recipient_email END as via_email
                FROM connections c
                JOIN users u ON u.email = CASE WHEN c.requester_email IN ({placeholders}) THEN c.recipient_email ELSE c.requester_email END
                WHERE (c.requester_email IN ({placeholders}) OR c.recipient_email IN ({placeholders}))
                  AND c.status = 'accepted'
                  AND u.email != ?
                  AND u.email NOT IN ({placeholders})
                LIMIT 20
            """, (*first_emails, *first_emails, *first_emails, *first_emails, user_id, *first_emails)).fetchall()

            for r in second_degree:
                nodes.append({"email": r['email'], "name": r['name'] or r['email'], "headline": r['headline'] or '', "degree": 2})
                edges.append({"from": r['via_email'], "to": r['email']})

    return jsonify({
        "status": "success",
        "nodes": nodes,
        "edges": edges
    })


@bp.route('/suggestions', methods=['GET'])
@require_auth
def suggestions(user_id):
    """Suggest users to connect with (not already connected)."""
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        # Get users not connected and not self, limit 10
        users = conn.execute("""
            SELECT u.email, u.name, u.headline, u.role
            FROM users u
            WHERE u.email != ?
              AND u.email NOT IN (
                  SELECT CASE WHEN requester_email = ? THEN recipient_email ELSE requester_email END
                  FROM connections
                  WHERE (requester_email = ? OR recipient_email = ?) AND status IN ('accepted', 'pending')
              )
            ORDER BY RANDOM()
            LIMIT 10
        """, (user_id, user_id, user_id, user_id)).fetchall()

    return jsonify({
        "status": "success",
        "suggestions": [dict(u) for u in users]
    })
