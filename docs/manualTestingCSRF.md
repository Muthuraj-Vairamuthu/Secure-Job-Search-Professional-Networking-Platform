# Manual Testing Guide: CSRF Protection

> **Prerequisites**: Server running (`python3 backend/api/app.py`), at least 1 registered user with TOTP.

---

## Table of Contents

1. [CSRF Token Generation on Login](#1-csrf-token-generation-on-login)
2. [Automatic CSRF Header Injection](#2-automatic-csrf-header-injection)
3. [CSRF Rejection Tests](#3-csrf-rejection-tests)
4. [CSRF Token Rotation](#4-csrf-token-rotation)
5. [Exempt Endpoints](#5-exempt-endpoints)
6. [Negative Tests](#6-negative-tests)

---

## 1. CSRF Token Generation on Login

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1.1 | Log in via `auth.html` | Login succeeds |
| 1.2 | Open browser DevTools → Application → Cookies | Two cookies visible |
| 1.3 | Check `session_id` cookie | `HttpOnly: ✓`, `Secure: ✓`, `SameSite: Strict` |
| 1.4 | Check `csrf_token` cookie | `HttpOnly: ✗` (JS-readable), `Secure: ✓`, `SameSite: Strict` |
| 1.5 | Verify `csrf_token` is a 64-character hex string | 256-bit token |

```bash
# Via curl: after login, check Set-Cookie headers
curl -sI -X POST http://localhost:8000/api/v1/auth/login/verify \
  -H "Content-Type: application/json" \
  -d '{"mfa_token": "<MFA>", "totp_code": "<CODE>"}' 2>&1 | grep -i "set-cookie"

# Expected: Two Set-Cookie headers:
# Set-Cookie: session_id=...; HttpOnly; Secure; SameSite=Strict; Max-Age=1800; Path=/
# Set-Cookie: csrf_token=<64-hex-chars>; Secure; SameSite=Strict; Max-Age=1800; Path=/
```

### Database Verification

```bash
sqlite3 backend/data/secure_app.db \
  "SELECT session_hash, csrf_token FROM sessions ORDER BY id DESC LIMIT 1;"

# csrf_token should be a 64-char hex string matching the cookie value
```

---

## 2. Automatic CSRF Header Injection

| Step | Action | Expected Result |
|------|--------|-----------------|
| 2.1 | Log in, navigate to `profile.html` | Page loads |
| 2.2 | Open DevTools → Network tab | |
| 2.3 | Edit your profile (any field, click save) | PUT request fires |
| 2.4 | Click on the PUT request → Headers | `X-CSRF-Token: <64-hex-chars>` present in Request Headers |
| 2.5 | Upload a resume | POST request fires with `X-CSRF-Token` header |
| 2.6 | Delete a resume | DELETE request fires with `X-CSRF-Token` header |

**All POST/PUT/DELETE requests from the frontend should automatically include the `X-CSRF-Token` header** — you should NOT need to manually add it anywhere.

---

## 3. CSRF Rejection Tests

### 3a. Missing CSRF Token

```bash
# Make a POST request WITHOUT the X-CSRF-Token header
curl -s -X POST http://localhost:8000/api/v1/users/resumes \
  --cookie "session_id=<SESSION>" \
  -F "resume=@test.pdf" | python3 -m json.tool

# Expected:
# {"status": "error", "message": "Missing CSRF token"}
# HTTP 403
```

### 3b. Invalid CSRF Token

```bash
# Make a POST request WITH a wrong X-CSRF-Token
curl -s -X POST http://localhost:8000/api/v1/users/resumes \
  --cookie "session_id=<SESSION>" \
  -H "X-CSRF-Token: aaaa_wrong_token_bbbb" \
  -F "resume=@test.pdf" | python3 -m json.tool

# Expected:
# {"status": "error", "message": "Invalid CSRF token"}
# HTTP 403
```

### 3c. Valid CSRF Token

```bash
# Get the CSRF token from the cookie (visible in DevTools or DB)
CSRF=$(sqlite3 backend/data/secure_app.db "SELECT csrf_token FROM sessions ORDER BY id DESC LIMIT 1;")

# Make a POST request WITH the correct X-CSRF-Token
curl -s -X PUT http://localhost:8000/api/v1/users/me \
  --cookie "session_id=<SESSION>" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{"name": "Test User"}' | python3 -m json.tool

# Expected:
# {"status": "success", ...}
```

---

## 4. CSRF Token Rotation

| Step | Action | Expected Result |
|------|--------|-----------------|
| 4.1 | Note the current `csrf_token` cookie value | |
| 4.2 | Call `POST /api/v1/auth/session/rotate` | New session + new CSRF token |
| 4.3 | Check the `csrf_token` cookie | **Different value** from step 4.1 |
| 4.4 | Try using the OLD CSRF token on a POST | 403 "Invalid CSRF token" |
| 4.5 | Use the NEW CSRF token | Request succeeds |

---

## 5. Exempt Endpoints

These endpoints should work **without** a CSRF token:

| Endpoint | Method | Reason |
|----------|--------|--------|
| `/api/v1/auth/register` | POST | Pre-authentication |
| `/api/v1/auth/register/verify` | POST | Pre-authentication |
| `/api/v1/auth/login` | POST | Pre-authentication |
| `/api/v1/auth/login/verify` | POST | Creating the session/token |
| `/api/v1/auth/session/rotate` | POST | Generating new token |
| `/api/v1/auth/logout` | POST | Destroying session |

```bash
# Test: register should work without CSRF
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "test@test.com", "password": "TestPass1!"}' | python3 -m json.tool

# Expected: Normal response (pending_mfa or error), NOT "Missing CSRF token"
```

---

## 6. Negative Tests

| Step | Action | Expected Result |
|------|--------|-----------------|
| 6.1 | Send POST without any cookies | 403 "Missing CSRF token" (no session → no CSRF) |
| 6.2 | Send POST with session but no X-CSRF-Token | 403 "Missing CSRF token" |
| 6.3 | Send POST with wrong X-CSRF-Token | 403 "Invalid CSRF token" |
| 6.4 | Send GET with no X-CSRF-Token | 200 OK (GET is exempt) |
| 6.5 | Send POST to `/api/v1/auth/login` with no token | Normal response (auth is exempt) |
| 6.6 | After logout, csrf_token cookie is cleared | No csrf_token cookie in DevTools |

### Simulated CSRF Attack

```bash
# Attacker's page would do:
# <form method="POST" action="http://localhost:8000/api/v1/users/me">
#   <input name="name" value="Hacked">
# </form>
# <script>document.forms[0].submit()</script>
#
# This would fail because:
# 1. SameSite=Strict prevents the session_id cookie from being sent
# 2. Even if it were sent, there's no X-CSRF-Token header
# Result: 403 Forbidden
```

---

## Quick Verification Checklist

- [ ] Login sets `csrf_token` cookie (non-HttpOnly, 64 hex chars)
- [ ] Login sets `session_id` cookie (HttpOnly)
- [ ] CSRF token stored in `sessions.csrf_token` column
- [ ] All frontend POST/PUT/DELETE include `X-CSRF-Token` header automatically
- [ ] POST without `X-CSRF-Token` returns 403
- [ ] POST with wrong `X-CSRF-Token` returns 403
- [ ] POST with correct `X-CSRF-Token` succeeds
- [ ] Auth endpoints work without CSRF token
- [ ] Session rotation generates new CSRF token
- [ ] Old CSRF token rejected after rotation
- [ ] Logout clears `csrf_token` cookie
