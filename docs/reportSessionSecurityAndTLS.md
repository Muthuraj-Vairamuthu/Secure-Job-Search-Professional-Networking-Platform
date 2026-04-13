# Implementation Report: Session Security & HTTPS/TLS Deployment

## Overview

This report documents the implementation of two security mandates:

1. **Session Security** — Session binding to IP + User-Agent, session rotation on privilege elevation
2. **HTTPS/TLS Deployment** — Self-signed TLS certificates, Nginx reverse proxy configuration, secure cookie flags

---

## 1. Session Security

### 1a. Session Binding (IP + User-Agent)

#### Schema Changes (`core/db.py`)

Two columns added to the `sessions` table:

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `client_ip` | TEXT | `''` | Client IP at time of login |
| `user_agent` | TEXT | `''` | Browser User-Agent string at time of login |

ALTER TABLE migration ensures existing databases are updated silently.

#### Binding on Login (`routes/auth.py`)

When a user completes MFA verification (`POST /api/v1/auth/login/verify`):
1. `client_ip` is captured from `X-Forwarded-For` or `remote_addr`
2. `user_agent` is captured from the `User-Agent` request header
3. Both are stored in the session row via `UPDATE sessions SET ... WHERE session_hash=?`

#### Validation on Every Request (`core/db.py` — `require_auth`)

The `require_auth` decorator now performs two additional checks after session lookup:

1. **IP Binding Check**: If `session.client_ip` is non-empty and doesn't match the current request's IP → return 401 + log `SESSION_IP_MISMATCH`
2. **User-Agent Binding Check**: If `session.user_agent` is non-empty and doesn't match the current `User-Agent` header → return 401 + log `SESSION_UA_MISMATCH`

Both violations are logged to the tamper-evident audit trail before the session is invalidated.

**Backward compatibility**: Sessions created before this feature was added have empty `client_ip` and `user_agent` values, so the checks are skipped (empty string is falsy).

### 1b. Session Rotation on Privilege Elevation

#### Rotation Endpoint (`POST /api/v1/auth/session/rotate`)

A dedicated endpoint for session ID rotation:

1. Reads the current session from the cookie
2. Generates a new `secrets.token_hex(32)` session ID
3. Deletes the old session row from the database
4. Creates a new session row with the same `user_id` and `role`, but a new hash, fresh timestamps, and updated IP/UA binding
5. Sets the new session cookie with `secure=True`, `httponly=True`, `samesite=Strict`
6. Logs `SESSION_ROTATED` to the audit trail

**When to call this**: After any privilege elevation (e.g., role change from `user` to `admin`, or after re-authenticating with MFA for a sensitive action).

**MFA already rotates**: The auth_secTOTP module generates a new session token on each successful MFA verification (login step 2), so MFA completion already provides session rotation inherently.

---

## 2. HTTPS/TLS Deployment

### 2a. Self-Signed TLS Certificate

Generated using OpenSSL:

```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout backend/certs/server.key \
  -out backend/certs/server.crt \
  -subj "/C=US/ST=Arizona/L=Tempe/O=FCS Group 19/OU=CSE345/CN=localhost"
```

| Property | Value |
|----------|-------|
| Algorithm | RSA-2048 |
| Validity | 365 days |
| Subject CN | `localhost` |
| Organization | FCS Group 19 |
| OU | CSE345 |
| Location | backend/certs/ |

### 2b. Nginx Configuration (`backend/nginx.conf`)

Full TLS termination reverse proxy configuration:

| Feature | Setting |
|---------|---------|
| **HTTP → HTTPS redirect** | Port 80 redirects to 443 with 301 |
| **TLS Protocols** | TLSv1.2 and TLSv1.3 only |
| **Cipher Suite** | `HIGH:!aNULL:!MD5:!RC4` |
| **Server Cipher Preference** | Enabled |
| **Session Cache** | Shared, 10MB, 10-minute timeout |
| **HSTS** | `max-age=31536000; includeSubDomains` |
| **X-Content-Type-Options** | `nosniff` |
| **X-Frame-Options** | `DENY` |
| **X-XSS-Protection** | `1; mode=block` |
| **Referrer-Policy** | `strict-origin-when-cross-origin` |
| **API Proxy** | `/api/` → `http://127.0.0.1:8000` |
| **Static Files** | Served directly from `frontend/public/`, `frontend/css/`, `frontend/js/` |
| **Proxy Headers** | `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto` forwarded |

### 2c. Secure Cookie Flags

All cookies in `routes/auth.py` are set with:

```python
resp.set_cookie('session_id', session_id,
    httponly=True,     # Prevents JavaScript access (XSS protection)
    secure=True,       # Only sent over HTTPS
    samesite='Strict', # Prevents CSRF via cross-origin requests
    max_age=1800       # 30-minute expiry
)
```

This was already partially in place (`secure=True` was added in a prior bug fix); this update confirms and standardizes it across all cookie-setting paths (login, rotation, logout).

---

## Deployment Instructions

### Quick Start (Development)

```bash
# Start the Flask backend
cd backend/api && python3 app.py
```

### Production Deployment

```bash
# 1. Install nginx
brew install nginx  # macOS
# or: sudo apt install nginx  # Ubuntu

# 2. Copy TLS certificates
sudo mkdir -p /etc/nginx/ssl
sudo cp backend/certs/server.crt /etc/nginx/ssl/
sudo cp backend/certs/server.key /etc/nginx/ssl/

# 3. Copy nginx config
sudo cp backend/nginx.conf /etc/nginx/conf.d/fcs_group19.conf

# 4. Test and reload nginx
sudo nginx -t
sudo nginx -s reload  # macOS
# or: sudo systemctl reload nginx  # Linux

# 5. Start Gunicorn backend
cd backend/api && gunicorn app:app -b 127.0.0.1:8000 --workers 4

# 6. Access: https://localhost
```

---

## Files Changed / Created

| File | Change |
|------|--------|
| `backend/api/core/db.py` | Added `client_ip`, `user_agent` to sessions table; updated `require_auth` for IP+UA validation; added `log_action_raw` helper |
| `backend/api/routes/auth.py` | Session binding on login; `POST /session/rotate` endpoint; standardized secure cookies |
| `backend/certs/server.crt` | **NEW** — Self-signed X.509 TLS certificate (RSA-2048, 365 days) |
| `backend/certs/server.key` | **NEW** — RSA-2048 private key for TLS |
| `backend/nginx.conf` | **NEW** — Full Nginx config with TLS termination, security headers, reverse proxy |
