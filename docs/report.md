# Implementation Report: Secure Job Search & Professional Networking Platform

This report details the currently implemented features of the application, evaluated against the CSE 345/545 Course Project Requirements (April Milestone).

---

## Architecture / Framework

| Layer | Technology |
|-------|-----------|
| Language | Python 3 with Flask 3.0.3 |
| Database | SQLite (WAL mode, parameterized queries throughout) |
| Frontend | Vanilla HTML/CSS/JS, Inter font, glassmorphism UI |
| Auth Crypto | `argon2-cffi` (Argon2id), `pyotp` (TOTP), `cryptography` (Fernet + AES-256-GCM) |
| Deployment | Gunicorn via `wsgi.py`, CORS enabled |

---

## A. User Profiles and Connections — ⚠️ PARTIAL

### ✅ Implemented
- **Profile CRUD**: Users can view (`GET /api/v1/users/me`) and update (`PUT /api/v1/users/me`) their profiles (name, headline, location, bio). Email and role captured at signup.
- **Data Persistence**: Profiles stored in the `users` table with fields: email, name, bio, location, headline, role.
- **Profile Page (Frontend)**: `profile.html` loads profile data dynamically from the API, displays avatar, bio, role badge, and provides edit/logout buttons.

### ❌ NOT Implemented
- **Field-Level Privacy Controls**: The `users` table has no `privacy_settings` columns. The profile-level privacy dropdown in `profile.html` (line 76–81) is a **dead UI widget** — it has no backend binding; changes are not saved or enforced.
- **Professional Connections Workflow**: No `connections` table exists. No API endpoints for send/accept/remove connection requests. `network.html` is **entirely static/hardcoded** with placeholder data (Alice Smith, Bob Jones, etc.) and non-functional Accept/Ignore/Connect buttons.
- **Connection Graph**: The SVG visualization in `network.html` is a **static CSS mockup**. No backend endpoint to retrieve connection data.
- **Profile Views Tracking**: No `profile_views` table. The analytics section in `profile.html` (lines 154–166) shows **hardcoded "142 profile views"**. The "Allow viewers to see I viewed them" checkbox is non-functional.

---

## B. Company Pages and Job Posting — ✅ IMPLEMENTED

### ✅ Implemented
- **Company Pages**: Recruiter-role users can create (`POST /api/v1/companies`), update (`PUT /api/v1/companies/<id>`), list all (`GET /api/v1/companies`), view single (`GET /api/v1/companies/<id>`), and list own (`GET /api/v1/companies/me`).
- **Job Listings**: Recruiters can post jobs (`POST /api/v1/jobs`) linked to their companies. Fields: title, description, skills, location, job_type, salary range, deadline.
- **Access Control**: Company creation restricted to recruiters via `@require_recruiter` decorator. Updates verify ownership via `owner_email`.
- **Audit**: Company creation/update and job post/update/delete are logged via `log_action`.
- **Frontend**: `company.html` (31KB) exists with full UI. `jobs.html` (17KB) includes search filters and job listing display.

---

## C. Job Search and Application Tracking — ✅ IMPLEMENTED

### ✅ Implemented
- **Job Search**: `GET /api/v1/jobs` supports keyword matching (title + description + skills), location, job_type, and company_name filters, all using parameterized LIKE queries.
- **Application Workflow**: Candidates apply via `POST /api/v1/applications` with resume_id and cover_note. Duplicate application enforcement via `UNIQUE(job_id, applicant_email)`.
- **Application Tracking**: Candidates view their applications (`GET /api/v1/applications/me`). Recruiters view applicants per job (`GET /api/v1/applications/job/<job_id>`).
- **Status Management**: Recruiters update statuses (`PUT /api/v1/applications/<app_id>/status`) to Applied, Reviewed, Interviewed, Rejected, or Offer. Recruiter notes supported.
- **Validation**: Active job check before apply; resume ownership verification; recruiter company-ownership check before status update.

---

## D. Secure Resume Upload and Storage — ✅ IMPLEMENTED

### ✅ Implemented
- **Strict File Validation** (`secureResumeUpload.py`):
  - Extension whitelist (`.pdf`, `.doc`, `.docx`).
  - Double-extension attack guard (`filename.count('.') > 1`).
  - 5 MB size limit enforcement.
  - Magic-byte header verification against declared extension.
  - Optional libmagic MIME type check.
- **Metadata Scrubbing**: PDF metadata stripped via PyMuPDF; DOCX core.xml replaced with blank template.
- **AES-256-GCM Encryption at Rest**: Per-file random 32-byte key + 12-byte nonce. Ciphertext written to disk with 0o600 permissions. Keys stored separately in 0o400 files.
- **Integrity Verification**: SHA-256 hash of ciphertext stored in DB and verified before every download.
- **Granular Access Control**: Downloads restricted to owner. Visibility toggle (private/public). Secure deletion overwrites file with zeros before unlinking.
- **API Endpoints**: Upload (`POST /api/v1/users/resumes`), list (`GET /api/v1/users/resumes`), download (`GET /api/v1/users/resumes/<id>/download`), delete (`DELETE /api/v1/users/resumes/<id>`).
- **Frontend**: `profile.html` has functional resume upload via FormData, dynamic resume listing, and download/delete buttons.
- **Secure Response Headers**: `Content-Disposition: attachment`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, CSP `default-src 'none'`.

### ⚠️ Issues Found
- **Frontend URL mismatch**: `profile.html` download calls `/api/profile/download_resume/<id>` (line 255) and delete calls `/api/profile/delete_resume/<id>` (line 261), but actual backend routes are `/api/v1/users/resumes/<id>/download` and `/api/v1/users/resumes/<id>` — **download and delete are broken from the UI**.
- **`resume.html` page is non-functional**: The drag-and-drop zone calls `alert('File Picker Placeholder')` and does not actually upload. Stored documents section is hardcoded.

---

## E. Secure Messaging — ✅ IMPLEMENTED

### ✅ Implemented
- **Direct and Group Chats**: Backend supports creating direct (1-to-1) and group conversations (`POST /api/v1/messages/conversations`). Schema: `conversations`, `conversation_members`, `messages` tables.
- **End-to-End Encryption (E2EE)**: Server only stores `encrypted_content` and `iv`. Frontend (`messages.html`) implements client-side AES-256-GCM encryption using Web Crypto API with PBKDF2 key derivation.
- **Key Distribution**: Users can publish public keys (`POST /api/v1/messages/keys`) and retrieve others' keys (`GET /api/v1/messages/keys/<email>`).
- **Conversation Management**: List conversations with message counts/last message timestamp. Add members to group chats. Membership verification before message access.
- **Real-time Polling**: Frontend polls for new messages every 3 seconds.
- **Frontend**: Full-featured `messages.html` (564 lines) with conversation sidebar, chat window, new conversation modal, add member modal, and E2EE badge indicators.
- **XSS Protection**: Messages are rendered via `escapeHtml()` function using `textContent`.

### ⚠️ Issues Found
- **Frontend URL mismatch**: `messages.html` calls `/api/messages/conversations/${convId}` (line 324, 384, 399) and `/api/messages/users` (line 440, 513), but the actual backend routes are `/api/v1/messages/conversations/<id>/messages` and `/api/v1/messages/users` — **fetching/sending messages is broken from the frontend**.
- **Simplified E2EE**: Key derivation uses a deterministic string (`e2ee-conv-${convId}-shared-secret`) rather than actual ECDH key exchange. This means any client who knows the conversation ID can derive the key. Acceptable as a demonstration, but should be documented as a simplification.

---

## F. Authentication and Account Security — ✅ IMPLEMENTED

### ✅ Implemented
- **Registration**: Two-step process. Step 1 validates inputs and generates TOTP secret. Step 2 verifies TOTP code before committing user to DB. Ghost accounts prevented.
- **Argon2id Password Hashing**: OWASP-recommended config (memory_cost=65536, time_cost=3, parallelism=4). Plaintext NEVER stored.
- **Mandatory TOTP (MFA)**: TOTP enrollment forced at signup. Login Step 1 verifies password, Step 2 verifies TOTP. Secrets encrypted at rest with Fernet.
- **Session Management**: 64-byte `secrets.token_urlsafe` session tokens. Stored as SHA-256 hash in DB. 30-minute expiration. HttpOnly + SameSite=Strict cookies.
- **Timing Attack Prevention**: Dummy Argon2 hash executed when user not found (lines 293-297).
- **Brute Force Protection**: Per-account exponential lockout (5 attempts → 5min, 10 → 30min, 20 → permanent). Per-IP throttling (20 failures/30min).
- **TOTP Replay Attack Prevention**: `last_mfa_window` tracked and enforced.
- **Auto Rehash**: If Argon2 config changes, hashes are transparently upgraded on login.
- **Password Change**: Full credential change flow with MFA verification, password reuse prevention, policy enforcement, rate limiting.
- **Audit Trailing**: All auth events logged (login attempts, failures, registrations, rate limits, MFA events, password changes).
- **Frontend**: `auth.html` has full 2-step login/signup UI with OTP input group, step indicators, auto-advance.

### ❌ NOT Implemented
- **Email/Mobile OTP Verification**: No SMTP or SMS integration. `is_verified` field exists but remains `False` (verification check at login line 315-316 is commented out). Verification tokens are generated but never validated.
- **Virtual Keyboard**: The "Use Virtual Keyboard" link in `auth.html` (line 142) just calls `alert('Virtual Keyboard triggered')`. No actual virtual keyboard implementation.

---

## G. Admin and Moderation — ⚠️ PARTIAL

### ✅ Implemented
- **RBAC**: Three roles (user, recruiter, admin) enforced via `@require_auth` and `@require_recruiter` decorators in `core/db.py`.
- **Admin Dashboard API**: `GET /api/v1/admin/dashboard` returns users, audit logs, resumes, sessions, companies, jobs, and applications.
- **Admin Frontend**: `admin.html` (562 lines) renders tabbed views for Users, Companies, Jobs, Applications, Audit Log, Resumes, and Sessions with stat cards.

### ⚠️ Issues Found
- **No admin role check**: The admin dashboard endpoint (`GET /api/v1/admin/dashboard`) only uses `@require_auth` — **ANY authenticated user can access the admin dashboard**. There is no `@require_admin` decorator.
- **No `require_admin` decorator exists**: While `require_recruiter` exists, there is no equivalent admin check anywhere in the codebase.

### ❌ NOT Implemented
- **Suspend/Delete Users**: No admin endpoints to suspend or delete user accounts. No suspend/delete buttons in `admin.html`.
- **Content Moderation**: No report handling, content flagging, or moderation workflows.

---

## H. Security Mandates — ⚠️ PARTIAL

### ✅ Implemented
- **SQL Injection Defense**: All queries use parameterized inputs (`?` placeholders) throughout the entire codebase. No string concatenation in SQL.
- **Password Hashing**: Argon2id with strong settings. Plaintext never stored. Reuse prevention on change.
- **Basic Audit Logging**: `log_action()` in `core/db.py` logs to `audit_logs` table with email, IP, event, timestamp. Resume module has separate JSONL file logging.
- **XSS Protection (Partial)**: Messages use `escapeHtml()`. Profile updates filter allowed fields. Output encoding in admin dashboard.

### ❌ NOT Implemented
- **PKI Integration (2 functions required)**:
  - The assignment requires **at least two security-critical functions** using PKI.
  - **Current state**: Public key publishing/retrieval exists for E2EE key exchange, but no actual PKI verification (no certificate issuance, no message signing, no resume integrity signatures, no company verification).
  - **Missing**: Resume digital signatures, company CA certificates, message non-repudiation, or any function that validates certificates.
- **OTP Virtual Keyboard**:
  - Required for at least two high-risk actions (password reset, resume download, account deletion).
  - **Current state**: `auth.html` has a "Use Virtual Keyboard" placeholder that shows an `alert()`. No actual virtual keyboard component exists. No OTP keyboard linked to resume downloads or account deletions.
- **Tamper-Evident Logging**:
  - Required: hash chaining or private blockchain.
  - **Current state**: `audit_logs` table is a plain append-only table with NO hash chaining. JSONL log in resume module has no hash chaining either. Logs can be tampered with undetected.
- **CSRF Protection**:
  - **Current state**: `CORS(app)` is enabled with **default settings (allows all origins)**. No CSRF tokens generated or validated. Session cookies are `SameSite=Strict` which provides *some* CSRF protection in modern browsers, but the assignment specifically requires CSRF tokens.
- **Session Fixation / Hijacking Prevention**:
  - Session tokens are regenerated after MFA completion, which is good.
  - **Missing**: Session IDs do not rotate on privilege escalation (e.g., role change). No session binding to IP or user-agent.
- **HTTPS / TLS**:
  - No self-signed certificate configuration. No Nginx config. Flask runs on HTTP (`app.run(port=8000, debug=False)`). The `scripts/server.py` also runs plain HTTP.
  - Session cookie lacks `Secure=True` flag (line 71 in `routes/auth.py`).

---

## Bugs Found During Audit

| # | Severity | File | Issue |
|---|----------|------|-------|
| 1 | 🔴 HIGH | `routes/admin.py` | Admin dashboard has no admin role check — any authenticated user can access it |
| 2 | 🔴 HIGH | `app.py` | `CORS(app)` with default settings allows ALL origins to make credentialed requests |
| 3 | 🟡 MED | `profile.html:255,261` | Resume download/delete URLs use old route paths (`/api/profile/...`) instead of `/api/v1/users/resumes/...` — buttons are broken |
| 4 | 🟡 MED | `messages.html:324,384,399,440,513` | Message fetch/send/search URLs use `api/messages/` instead of `/api/v1/messages/` — messaging is broken from frontend |
| 5 | 🟡 MED | `routes/auth.py:71` | Session cookie missing `Secure=True` flag |
| 6 | 🟡 MED | `core/db.py:185` | `conn.commit()` called after `with` block exits (connection may be closed) |
| 7 | 🟢 LOW | `secureResumeUpload.py:544` | `set_resume_visibility` checks `record["owner_user_id"] != user["email"]` but validate_session returns `user_id`, not `email` |
| 8 | 🟢 LOW | `tests/test_integration.py` | All API URLs use old route paths (`/api/auth/signup`, `/api/profile/upload_resume`, etc.) — tests will 404 |
| 9 | 🟢 LOW | `resume.html` | Upload zone is non-functional (calls alert placeholder) |
| 10 | 🟢 LOW | `network.html` | Entire page is static mockup with hardcoded data |

---

## Summary Scorecard

| Requirement | Status | Notes |
|-------------|--------|-------|
| **A.** User Profiles | ⚠️ Partial | CRUD works; connections, privacy, views missing |
| **B.** Company Pages | ✅ Done | Fully functional CRUD with access control |
| **C.** Job Search & Apps | ✅ Done | Search, apply, track, status updates all work |
| **D.** Resume Upload | ✅ Done (bugs) | Full security pipeline; frontend URLs broken |
| **E.** Messaging | ✅ Done (bugs) | E2EE architecture in place; frontend URLs broken |
| **F.** Authentication | ✅ Done (partial) | Argon2 + TOTP + sessions; email OTP & virtual keyboard missing |
| **G.** Admin & RBAC | ⚠️ Partial | Dashboard exists but no admin role enforcement or user management |
| **H.** Security Mandates | ⚠️ Partial | SQLi + hashing done; PKI, virtual keyboard, hash chaining, CSRF, TLS missing |
| **Bonus: Blockchain** | ❌ Not started | |
| **Bonus: Resume AI** | ❌ Not started | |
