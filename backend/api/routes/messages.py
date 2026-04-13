import sqlite3
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from core.db import DB_NAME, require_auth, log_action
import pki

bp = Blueprint('messages', __name__)

@bp.route('/keys', methods=['POST'])
@require_auth
def publish_key(user_id):
    """Store user's public key for E2EE key exchange."""
    data = request.json
    public_key = data.get('public_key', '')
    if not public_key:
        return jsonify({"status": "error", "message": "public_key is required"}), 400
    with sqlite3.connect(DB_NAME) as conn:
        try:
            conn.execute("ALTER TABLE users ADD COLUMN public_key TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # Column already exists
        conn.execute("UPDATE users SET public_key=? WHERE email=?", (public_key, user_id))
    return jsonify({"status": "success", "message": "Public key published"})

@bp.route('/keys/<path:email>', methods=['GET'])
@require_auth
def get_user_key(user_id, email):
    """Get a user's public key for E2EE."""
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        user = conn.execute("SELECT email, name, public_key FROM users WHERE email=?", (email,)).fetchone()
    if not user:
        return jsonify({"status": "error", "message": "User not found"}), 404
    return jsonify({
        "status": "success",
        "email": user['email'],
        "name": user['name'],
        "public_key": user['public_key'] if 'public_key' in user.keys() and user['public_key'] else ''
    })

@bp.route('/conversations', methods=['GET'])
@require_auth
def list_conversations(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        convos = conn.execute(
            """SELECT c.*, 
               (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) as message_count,
               (SELECT m2.timestamp FROM messages m2 WHERE m2.conversation_id=c.id ORDER BY m2.id DESC LIMIT 1) as last_message_time
               FROM conversations c
               JOIN conversation_members cm ON c.id=cm.conversation_id
               WHERE cm.user_email=?
               ORDER BY last_message_time DESC NULLS LAST""",
            (user_id,)
        ).fetchall()
        result = []
        for convo in convos:
            convo_dict = dict(convo)
            # Get members
            members = conn.execute(
                "SELECT cm.user_email, u.name FROM conversation_members cm JOIN users u ON cm.user_email=u.email WHERE cm.conversation_id=?",
                (convo['id'],)
            ).fetchall()
            convo_dict['members'] = [dict(m) for m in members]
            # Get last message preview
            last_msg = conn.execute(
                "SELECT sender_email, encrypted_content, timestamp FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT 1",
                (convo['id'],)
            ).fetchone()
            convo_dict['last_message'] = dict(last_msg) if last_msg else None
            result.append(convo_dict)
    return jsonify({"status": "success", "conversations": result})

@bp.route('/conversations', methods=['POST'])
@require_auth
def create_conversation(user_id):
    data = request.json
    conv_type = data.get('type', 'direct')
    name = data.get('name', '').strip()
    participant_emails = data.get('participants', [])
    if not participant_emails:
        return jsonify({"status": "error", "message": "At least one participant required"}), 400
    # For direct messages, check if conversation already exists
    if conv_type == 'direct' and len(participant_emails) == 1:
        other_email = participant_emails[0]
        with sqlite3.connect(DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                """SELECT c.id FROM conversations c
                   WHERE c.type='direct'
                   AND c.id IN (SELECT conversation_id FROM conversation_members WHERE user_email=?)
                   AND c.id IN (SELECT conversation_id FROM conversation_members WHERE user_email=?)""",
                (user_id, other_email)
            ).fetchone()
        if existing:
            return jsonify({"status": "success", "conversation_id": existing['id'], "message": "Existing conversation"})
    # Verify all participants exist
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        for email in participant_emails:
            user_check = conn.execute("SELECT email FROM users WHERE email=?", (email,)).fetchone()
            if not user_check:
                return jsonify({"status": "error", "message": f"User {email} not found"}), 404
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute(
            "INSERT INTO conversations (type, name, created_at, created_by) VALUES (?,?,?,?)",
            (conv_type, name, now, user_id)
        )
        conv_id = cursor.lastrowid
        # Add creator as member
        conn.execute(
            "INSERT INTO conversation_members (conversation_id, user_email, joined_at) VALUES (?,?,?)",
            (conv_id, user_id, now)
        )
        # Add other participants
        for email in participant_emails:
            if email != user_id:
                conn.execute(
                    "INSERT INTO conversation_members (conversation_id, user_email, joined_at) VALUES (?,?,?)",
                    (conv_id, email, now)
                )
    log_action(user_id, f"CONVERSATION_CREATED: id={conv_id}, type={conv_type}")
    return jsonify({"status": "success", "conversation_id": conv_id, "message": "Conversation created"})

@bp.route('/conversations/<int:conv_id>/messages', methods=['GET'])
@require_auth
def get_messages(user_id, conv_id):
    # Verify user is a member
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        member = conn.execute(
            "SELECT * FROM conversation_members WHERE conversation_id=? AND user_email=?",
            (conv_id, user_id)
        ).fetchone()
    if not member:
        return jsonify({"status": "error", "message": "Not a member of this conversation"}), 403
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        messages = conn.execute(
            """SELECT m.*, u.name as sender_name
               FROM messages m JOIN users u ON m.sender_email=u.email
               WHERE m.conversation_id=?
               ORDER BY m.id ASC LIMIT ? OFFSET ?""",
            (conv_id, limit, offset)
        ).fetchall()
        conv = conn.execute("SELECT * FROM conversations WHERE id=?", (conv_id,)).fetchone()
        members = conn.execute(
            "SELECT cm.user_email, u.name, cm.public_key FROM conversation_members cm JOIN users u ON cm.user_email=u.email WHERE cm.conversation_id=?",
            (conv_id,)
        ).fetchall()
    return jsonify({
        "status": "success",
        "conversation": dict(conv) if conv else {},
        "members": [dict(m) for m in members],
        "messages": [dict(m) for m in messages],
        "pki_enabled": True
    })

@bp.route('/conversations/<int:conv_id>/messages', methods=['POST'])
@require_auth
def send_message(user_id, conv_id):
    # Verify membership
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        member = conn.execute(
            "SELECT * FROM conversation_members WHERE conversation_id=? AND user_email=?",
            (conv_id, user_id)
        ).fetchone()
    if not member:
        return jsonify({"status": "error", "message": "Not a member of this conversation"}), 403
    data = request.json
    encrypted_content = data.get('encrypted_content', '')
    iv = data.get('iv', '')
    if not encrypted_content:
        return jsonify({"status": "error", "message": "encrypted_content is required"}), 400

    # PKI: Sign the message content with the sender's RSA private key
    private_pem, _ = pki.get_or_create_keypair(DB_NAME, user_id)
    signature = pki.sign_data(private_pem, encrypted_content.encode('utf-8'))

    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute(
            "INSERT INTO messages (conversation_id, sender_email, encrypted_content, iv, signature, timestamp) VALUES (?,?,?,?,?,?)",
            (conv_id, user_id, encrypted_content, iv, signature, now)
        )
        msg_id = cursor.lastrowid
    log_action(user_id, f"MESSAGE_SENT_AND_SIGNED: conv_id={conv_id}")
    return jsonify({"status": "success", "message_id": msg_id, "timestamp": now, "pki_signed": True})

@bp.route('/conversations/<int:conv_id>/members', methods=['POST'])
@require_auth
def add_member(user_id, conv_id):
    # Only conversation creator can add members
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        conv = conn.execute("SELECT * FROM conversations WHERE id=? AND created_by=?", (conv_id, user_id)).fetchone()
    if not conv:
        return jsonify({"status": "error", "message": "Conversation not found or permission denied"}), 403
    data = request.json
    new_member_email = data.get('email', '').strip()
    if not new_member_email:
        return jsonify({"status": "error", "message": "email is required"}), 400
    # Verify user exists
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        user_check = conn.execute("SELECT email FROM users WHERE email=?", (new_member_email,)).fetchone()
    if not user_check:
        return jsonify({"status": "error", "message": "User not found"}), 404
    now = datetime.now(timezone.utc).isoformat()
    try:
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute(
                "INSERT INTO conversation_members (conversation_id, user_email, joined_at) VALUES (?,?,?)",
                (conv_id, new_member_email, now)
            )
    except sqlite3.IntegrityError:
        return jsonify({"status": "error", "message": "User is already a member"}), 409
    return jsonify({"status": "success", "message": f"{new_member_email} added to conversation"})

@bp.route('/users', methods=['GET'])
@require_auth
def search_users_for_messaging(user_id):
    """Search users to start a conversation with."""
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify({"status": "success", "users": []})
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        users = conn.execute(
            "SELECT email, name, headline, role FROM users WHERE email != ? AND (name LIKE ? OR email LIKE ?) LIMIT 20",
            (user_id, f"%{q}%", f"%{q}%")
        ).fetchall()
    return jsonify({"status": "success", "users": [dict(u) for u in users]})


@bp.route('/messages/<int:msg_id>/verify', methods=['GET'])
@require_auth
def verify_message_signature(user_id, msg_id):
    """Verify the digital signature of a specific message (PKI Function 2 — Non-Repudiation)."""
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        msg = conn.execute("SELECT * FROM messages WHERE id=?", (msg_id,)).fetchone()
        if not msg:
            return jsonify({"status": "error", "message": "Message not found"}), 404

        # Verify the requesting user is a member of the conversation
        member = conn.execute(
            "SELECT * FROM conversation_members WHERE conversation_id=? AND user_email=?",
            (msg['conversation_id'], user_id)
        ).fetchone()
        if not member:
            return jsonify({"status": "error", "message": "Not a member of this conversation"}), 403

        sig = msg['signature'] if 'signature' in msg.keys() else ''
        if not sig:
            return jsonify({
                "status": "success",
                "verified": False,
                "reason": "Message has no digital signature",
                "sender": msg['sender_email']
            })

        sender_pub_key = pki.get_public_key(DB_NAME, msg['sender_email'])
        if not sender_pub_key:
            return jsonify({
                "status": "success",
                "verified": False,
                "reason": "Sender's public key not found",
                "sender": msg['sender_email']
            })

        verified, reason = pki.verify_signature(
            sender_pub_key,
            msg['encrypted_content'].encode('utf-8'),
            sig
        )
        return jsonify({
            "status": "success",
            "verified": verified,
            "reason": reason,
            "sender": msg['sender_email'],
            "message_id": msg_id,
            "signature_algorithm": "RSA-2048-PSS-SHA256"
        })
