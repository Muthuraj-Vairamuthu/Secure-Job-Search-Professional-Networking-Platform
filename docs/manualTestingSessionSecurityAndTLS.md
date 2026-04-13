# Manual Testing Guide: Session Security & HTTPS/TLS Deployment

> **Prerequisites**: Server running (`python3 backend/api/app.py`), at least 1 registered user with TOTP.

---

## Table of Contents

1. [Session Binding (IP + User-Agent)](#1-session-binding-ip--user-agent)
2. [Session Rotation](#2-session-rotation)
3. [Secure Cookie Flags](#3-secure-cookie-flags)
4. [TLS Certificate Verification](#4-tls-certificate-verification)
5. [Nginx Deployment](#5-nginx-deployment)
6. [Negative Tests](#6-negative-tests)

---

## 1. Session Binding (IP + User-Agent)

### 1a. Verify Binding is Stored on Login

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1.1 | Log in normally via `auth.html` | Login succeeds, session cookie set |
| 1.2 | Check the session in the database | `client_ip` and `user_agent` are populated |

```bash
# Check session binding data
sqlite3 backend/data/secure_app.db \
  "SELECT session_hash, user_id, client_ip, user_agent FROM sessions ORDER BY id DESC LIMIT 3;"

# Expected: client_ip = '127.0.0.1' (or actual IP), user_agent = browser UA string
```

### 1b. Verify IP Binding

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1.3 | Log in from a browser | Session works |
| 1.4 | Use `curl` with the same session cookie but from a different context (different X-Forwarded-For) | |

```bash
# Simulate IP mismatch
curl -s http://localhost:8000/api/v1/users/me \
  --cookie "session_id=<SESSION>" \
  -H "X-Forwarded-For: 192.168.99.99" | python3 -m json.tool

# Expected: {"status": "error", "message": "Session invalidated: IP address changed"}
```

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1.5 | Check audit log | `SESSION_IP_MISMATCH` event logged |

### 1c. Verify User-Agent Binding

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1.6 | Log in from Chrome | Session works |
| 1.7 | Copy the session cookie and use it from `curl` (different UA) | |

```bash
# Simulate UA mismatch
curl -s http://localhost:8000/api/v1/users/me \
  --cookie "session_id=<SESSION>" \
  -H "User-Agent: EvilBot/1.0" | python3 -m json.tool

# Expected: {"status": "error", "message": "Session invalidated: device changed"}
```

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1.8 | Check audit log | `SESSION_UA_MISMATCH` event logged |

---

## 2. Session Rotation

### 2a. Manual Session Rotation

| Step | Action | Expected Result |
|------|--------|-----------------|
| 2.1 | Log in, note the `session_id` cookie value | |
| 2.2 | Call `POST /api/v1/auth/session/rotate` | New cookie set, old session deleted |

```bash
# Rotate session
curl -s -X POST http://localhost:8000/api/v1/auth/session/rotate \
  --cookie "session_id=<OLD_SESSION>" \
  -c - | python3 -m json.tool

# Expected:
# {"status": "success", "message": "Session rotated"}
# Set-Cookie header contains a NEW session_id
```

| Step | Action | Expected Result |
|------|--------|-----------------|
| 2.3 | Try using the OLD session cookie | 401 Invalid session |
| 2.4 | Use the NEW session cookie | Works (200 OK) |
| 2.5 | Check audit log | `SESSION_ROTATED` event logged |

### 2b. Verify Session Binding Preserved After Rotation

| Step | Action | Expected Result |
|------|--------|-----------------|
| 2.6 | Check the new session in DB after rotation | `client_ip` and `user_agent` updated to current values |

```bash
sqlite3 backend/data/secure_app.db \
  "SELECT session_hash, user_id, client_ip, user_agent FROM sessions ORDER BY id DESC LIMIT 1;"
```

---

## 3. Secure Cookie Flags

| Step | Action | Expected Result |
|------|--------|-----------------|
| 3.1 | Log in via browser | Cookie set |
| 3.2 | Open browser DevTools → Application → Cookies | Inspect `session_id` cookie |
| 3.3 | Check **HttpOnly** flag | `✓` (JavaScript cannot access) |
| 3.4 | Check **Secure** flag | `✓` (only sent over HTTPS) |
| 3.5 | Check **SameSite** flag | `Strict` |
| 3.6 | Check **Max-Age** | 1800 (30 minutes) |

```bash
# Verify via curl response headers
curl -sI -X POST http://localhost:8000/api/v1/auth/login/verify \
  -H "Content-Type: application/json" \
  -d '{"mfa_token": "...", "totp_code": "..."}' 2>&1 | grep -i "set-cookie"

# Expected: Set-Cookie: session_id=...; HttpOnly; Secure; SameSite=Strict; Max-Age=1800; Path=/
```

---

## 4. TLS Certificate Verification

| Step | Action | Expected Result |
|------|--------|-----------------|
| 4.1 | Verify certificate exists | Files present |
| 4.2 | Inspect certificate details | Correct subject and validity |

```bash
# Check certificate exists
ls -la backend/certs/server.crt backend/certs/server.key

# Inspect certificate
openssl x509 -in backend/certs/server.crt -noout -subject -dates -issuer

# Expected:
# subject= /C=US/ST=Arizona/L=Tempe/O=FCS Group 19/OU=CSE345/CN=localhost
# notBefore=Apr 12 ... 2026 GMT
# notAfter=Apr 12 ... 2027 GMT

# Verify key matches certificate
openssl x509 -noout -modulus -in backend/certs/server.crt | openssl md5
openssl rsa -noout -modulus -in backend/certs/server.key | openssl md5
# Both MD5 hashes should match
```

---

## 5. Nginx Deployment

### 5a. Test Nginx Config (Without Deploying)

```bash
# Validate the config syntax
nginx -t -c /Users/aditya/temp/vm/submission2/backend/nginx.conf 2>&1
# (May fail due to absolute path requirements — use instructions below for actual deployment)
```

### 5b. Full Deployment Test

| Step | Action | Expected Result |
|------|--------|-----------------|
| 5.1 | Copy certs to nginx ssl directory | |
| 5.2 | Copy config to nginx conf.d | |
| 5.3 | Start Gunicorn backend | Backend running on 8000 |
| 5.4 | Reload nginx | No errors |
| 5.5 | Access `http://localhost` | Redirects to `https://localhost` (301) |
| 5.6 | Access `https://localhost` | Page loads (browser may warn about self-signed cert) |
| 5.7 | Access `https://localhost/api/v1/auth/login` (POST) | Proxied to backend |

```bash
# Quick deployment
sudo mkdir -p /etc/nginx/ssl
sudo cp backend/certs/server.crt /etc/nginx/ssl/
sudo cp backend/certs/server.key /etc/nginx/ssl/
sudo cp backend/nginx.conf /etc/nginx/conf.d/fcs_group19.conf

# Start backend
cd backend/api && gunicorn app:app -b 127.0.0.1:8000 &

# Reload nginx
sudo nginx -s reload

# Test HTTPS
curl -sk https://localhost/ | head -5
# Expected: HTML content from index.html

# Test security headers
curl -skI https://localhost/ | grep -E "(Strict-Transport|X-Content-Type|X-Frame|X-XSS)"
# Expected:
# Strict-Transport-Security: max-age=31536000; includeSubDomains
# X-Content-Type-Options: nosniff
# X-Frame-Options: DENY
# X-XSS-Protection: 1; mode=block
```

### 5c. Verify HTTP to HTTPS Redirect

```bash
curl -sI http://localhost/ | head -3
# Expected:
# HTTP/1.1 301 Moved Permanently
# Location: https://localhost/
```

---

## 6. Negative Tests

| Step | Action | Expected Result |
|------|--------|-----------------|
| 6.1 | Steal session cookie and use from different IP | 401 "Session invalidated: IP address changed" |
| 6.2 | Steal session cookie and use from different browser | 401 "Session invalidated: device changed" |
| 6.3 | Use expired session cookie | 401 "Session expired" |
| 6.4 | Rotate session with invalid cookie | 401 "Invalid session" |
| 6.5 | Rotate session with no cookie | 401 "No active session" |
| 6.6 | Use old session after rotation | 401 "Invalid session" |
| 6.7 | Access `http://` when nginx is active | 301 redirect to `https://` |
| 6.8 | Try accessing with TLS 1.0/1.1 | Connection refused (only TLSv1.2+ allowed) |

```bash
# Test TLS version restriction
curl -sk --tls-max 1.1 https://localhost/ 2>&1
# Expected: SSL error or connection failure
```

---

## Quick Verification Checklist

### Session Security
- [ ] Sessions table has `client_ip` and `user_agent` columns
- [ ] Login stores IP + UA in session row
- [ ] Request from different IP returns 401 with `SESSION_IP_MISMATCH` logged
- [ ] Request from different UA returns 401 with `SESSION_UA_MISMATCH` logged
- [ ] `POST /api/v1/auth/session/rotate` generates new session, invalidates old
- [ ] Rotated session preserves IP+UA binding
- [ ] Session rotation is logged to audit trail

### HTTPS/TLS
- [ ] `backend/certs/server.crt` and `server.key` exist
- [ ] Certificate is valid for 365 days with `CN=localhost`
- [ ] `backend/nginx.conf` contains TLS termination config
- [ ] Cookie has `Secure`, `HttpOnly`, `SameSite=Strict` flags
- [ ] Nginx redirects HTTP → HTTPS
- [ ] Security headers (HSTS, X-Frame-Options, etc.) present
