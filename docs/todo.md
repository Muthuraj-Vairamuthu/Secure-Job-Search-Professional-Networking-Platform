# Development TODO List: Remaining Implementation Requirements

The following requirements from the assignment specifications are **missing or incomplete** and must be resolved before the final April Milestone Evaluation (April 30).

---

## ✅ Critical: Fix Existing Bugs First

These bugs broke currently "implemented" features — **all fixed**:

- [x] **Fix Admin Dashboard Authorization**: `routes/admin.py` now uses `@require_admin` decorator. Added `require_admin` to `core/db.py`.
- [x] **Fix CORS Configuration**: `CORS(app)` in `app.py` now restricted to `http://localhost:8000` and `https://localhost` with `supports_credentials=True`.
- [x] **Fix Resume Download/Delete URLs in Frontend**: `profile.html` now uses `/api/v1/users/resumes/<id>/download` and `/api/v1/users/resumes/<id>`.
- [x] **Fix Messaging URLs in Frontend**: `messages.html` now uses `/api/v1/messages/...` for all fetch calls (open, refresh, send, search, add member).
- [x] **Fix Session Cookie Security**: `routes/auth.py` `set_cookie()` now includes `secure=True`.
- [x] **Fix `log_action` in `core/db.py`**: `conn.commit()` moved inside the `with` block.
- [x] **Fix Integration Tests**: `tests/test_integration.py` updated to use `/api/v1/...` routes and proper session handling.

---

## ✅ Assignment Requirement: A. User Profiles and Connections

- [x] **Field-Level Privacy Controls**:
    - [x] Add privacy columns to `users` table (`privacy_profile`, `show_profile_views`).
    - [x] Create API endpoints `GET/PUT /api/v1/users/me/privacy` to read/update field visibility.
    - [x] Enforce privacy rules when other users view a profile (`GET /api/v1/users/profile/<email>` — filters fields based on connection status).
    - [x] Wire up the dropdown in `profile.html` to save settings via API with live feedback.
- [x] **Professional Connections Workflow**:
    - [x] Create `connections` table: `(id, requester_email, recipient_email, status, created_at, updated_at)` with UNIQUE constraint.
    - [x] API: `POST /api/v1/connections/request` — send connection request.
    - [x] API: `PUT /api/v1/connections/<id>/accept` — accept request (recipient only).
    - [x] API: `PUT /api/v1/connections/<id>/reject` — reject request (recipient only).
    - [x] API: `DELETE /api/v1/connections/<id>` — remove/cancel connection (either party).
    - [x] API: `GET /api/v1/connections` — list accepted, pending received, pending sent.
    - [x] Rewrote `network.html` — all buttons wired to real API calls with auto-reload.
- [x] **Limited Connection Graph**:
    - [x] API: `GET /api/v1/connections/graph` — returns 1st and 2nd degree connections with nodes/edges.
    - [x] Replaced static SVG mockup in `network.html` with radial SVG graph visualization.
- [x] **Profile Views Tracking**:
    - [x] Create `profile_views` table: `(id, viewer_email, viewed_email, timestamp)`.
    - [x] Track views when profile is accessed via `GET /api/v1/users/profile/<email>` (self-views excluded).
    - [x] Replaced hardcoded "142 profile views" in `profile.html` with live data from `GET /api/v1/users/me/views`.
    - [x] Implemented opt-out via `show_profile_views` setting (viewers toggle in profile analytics).

---

## 🟡 Assignment Requirement: F. Authentication Enhancements

- [ ] **Email/Mobile OTP Verification**:
    - [ ] Implement simulated email sending (e.g., SMTP with MailHog, or log-to-console mock). 
    - [ ] Uncomment and wire up the `is_verified` check in `auth_secTOTP.py` line 315–316.
    - [ ] Create endpoint to verify email token: `POST /api/v1/auth/verify-email`.

---

## 🟡 Assignment Requirement: G. Admin and Moderation

- [ ] **Create `require_admin` decorator** in `core/db.py` to check `role == 'admin'`.
- [ ] **Apply `require_admin`** to `GET /api/v1/admin/dashboard` in `routes/admin.py`.
- [ ] **Suspend User**: `PUT /api/v1/admin/users/<id>/suspend` — set a `suspended` flag or `locked_until` to a far-future date.
- [ ] **Delete User**: `DELETE /api/v1/admin/users/<id>` — remove user, their sessions, resumes (securely), applications, and conversation memberships.
- [ ] **Unsuspend User**: `PUT /api/v1/admin/users/<id>/unsuspend`.
- [ ] Add suspend/delete buttons to the Users table in `admin.html`.

---

## ✅ Assignment Requirement: H. Security Mandates (April Milestone)

### ✅ PKI Integration (2 functions required)
- [x] **Function 1 — Resume Digital Signatures**:
    - [x] Generate RSA-2048 key pair per user (lazy, on first use) — stored in `users.pki_private_key`, `users.pki_public_key`.
    - [x] On resume upload, sign the SHA-256 hash of the plaintext with the user's private key (RSA-PSS-SHA256).
    - [x] Store the base64 signature in `resumes.digital_signature`.
    - [x] On download: auto-verify, expose `X-PKI-Signature-Status` header. Dedicated endpoint: `GET /api/v1/users/resumes/<id>/verify`.
- [x] **Function 2 — Message Signing (Non-Repudiation)**:
    - [x] Sign each outgoing message's `encrypted_content` with the sender's RSA private key.
    - [x] Store base64 signature in `messages.signature` column.
    - [x] Dedicated verification: `GET /api/v1/messages/messages/<msg_id>/verify` — returns verified bool + reason.
- [x] **PKI Module**: `backend/api/pki.py` — key gen, sign, verify functions.
- [x] **User PKI Endpoint**: `GET /api/v1/users/me/pki` — retrieve/generate public key.

### ✅ OTP Virtual Keyboard
- [x] **Build Virtual Keyboard Component**:
    - [x] Created `frontend/js/virtual-keyboard.js` — randomized Fisher-Yates digit layout on each `show()`.
    - [x] Physical keyboard input blocked on overlay (keydown intercepted). Digits displayed as `●` bullets.
- [x] **Link to High-Risk Actions** (2 required, 3 implemented):
    - [x] **Login OTP**: `auth.html` login step 2 OTP inputs are `readonly`; green button opens virtual keyboard for entry.
    - [x] **Resume Download**: `profile.html` download button opens virtual keyboard → verifies via `POST /api/v1/admin/otp/verify` before allowing download.
    - [x] **Password Change**: New password change widget in `profile.html` requires OTP via virtual keyboard before submitting.
- [x] **OTP Verification Endpoint**: `POST /api/v1/admin/otp/verify` — verifies TOTP code for any high-risk action, logs success/failure.

### ✅ Tamper-Evident Logging (Hash Chaining)
- [x] **Refactored `audit_logs` table**: Added `log_hash TEXT` and `prev_hash TEXT` columns + ALTER TABLE migration.
- [x] **Refactored `log_action()` in `core/db.py`**:
    - Fetches the most recent log entry's `log_hash` (or `'GENESIS'` for first entry).
    - Computes `log_hash = SHA-256(prev_hash|email|event|timestamp|ip_address)`.
    - Stores both `log_hash` and `prev_hash` in the new row.
- [x] **Verification endpoint**: `GET /api/v1/admin/audit/verify` — walks the chain, reports broken links, admin-only.
- [x] **Verified**: New entries form proper GENESIS→hash→hash chain; tampering detected correctly.

### ✅ CSRF Protection
- [x] **Generate CSRF tokens**: `generate_csrf_token()` in `core/db.py` — 256-bit token via `secrets.token_hex(32)`, stored in `sessions.csrf_token`.
- [x] **Embed in responses**: Token set as JS-readable cookie `csrf_token` (non-HttpOnly, Secure, SameSite=Strict) on login + rotation. Cleared on logout.
- [x] **Validate on state-changing requests**: Global `@app.before_request` middleware in `app.py` validates `X-CSRF-Token` header on POST/PUT/DELETE/PATCH. Auth endpoints exempt. Constant-time comparison via `secrets.compare_digest()`.
- [x] **Frontend auto-injection**: `script.js` overrides `window.fetch` to auto-inject `X-CSRF-Token` from cookie — zero changes to existing fetch calls.

### ✅ Session Security
- [x] **Session rotation on privilege elevation**: `POST /api/v1/auth/session/rotate` — generates new session ID, deletes old, preserves user/role. MFA login already rotates ✅.
- [x] **Bind sessions to IP + User-Agent**: `client_ip` and `user_agent` stored in `sessions` table on login. `require_auth` validates on every request — returns 401 + logs `SESSION_IP_MISMATCH` / `SESSION_UA_MISMATCH` on mismatch.

### ✅ HTTPS / TLS Deployment
- [x] **Generated self-signed certificates**: `backend/certs/server.crt` + `server.key` (RSA-2048, 365 days, CN=localhost, O=FCS Group 19/CSE345).
- [x] **Configured Nginx**: `backend/nginx.conf` — TLS 1.2/1.3 termination, HSTS, security headers (X-Frame-Options, X-Content-Type-Options, X-XSS-Protection), HTTP→HTTPS redirect, reverse proxy to Gunicorn:8000.
- [x] **Secure cookie flags**: All `set_cookie` calls use `secure=True, httponly=True, samesite='Strict', max_age=1800`.

---

## 🟢 Bonus Items

- [ ] **Blockchain-Based Logging (+6%)**: Upgrade hash chaining into a local blockchain structure with blocks containing multiple log entries, Merkle roots, and proof-of-work or proof-of-authority.
- [ ] **Resume Parsing & Intelligent Matching (+2%)**: Use `spaCy` or regex to extract keywords/skills from uploaded PDFs. Match against job requirements. Surface match scores to recruiters on the applicant view.

---

## Priority Order for Implementation

1. 🔴 **Fix all existing bugs** (broken URLs, admin auth, CORS, etc.)
2. 🔴 **Tamper-Evident Logging** (hash chaining) — core security mandate
3. 🔴 **PKI Integration** (2 functions) — core security mandate
4. 🔴 **OTP Virtual Keyboard** (2 high-risk actions) — core security mandate
5. 🟡 **CSRF Protection** — security mandate
6. 🟡 **HTTPS/TLS with Nginx** — February milestone requirement still pending
7. 🟡 **Admin Suspend/Delete** — partial admin module
8. 🟡 **Professional Connections** — missing feature
9. 🟡 **Field-Level Privacy** — missing feature
10. 🟡 **Email OTP Verification** — missing feature
11. 🟡 **Profile Views Tracking** — missing feature
12. 🟢 Bonus: Blockchain logging
13. 🟢 Bonus: Resume parsing
