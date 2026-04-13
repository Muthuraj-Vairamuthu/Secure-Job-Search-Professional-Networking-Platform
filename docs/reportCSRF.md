# Implementation Report: CSRF Protection

## Overview

This report documents the implementation of **Cross-Site Request Forgery (CSRF) Protection** using the **Synchronizer Token Pattern**.

---

## Architecture

### Pattern: Synchronizer Token (Double Submit)

1. **Token Generation**: On login (MFA verification), the server generates a cryptographically secure CSRF token (`secrets.token_hex(32)` = 64 hex chars / 256 bits)
2. **Token Storage**: Stored in the `sessions.csrf_token` column (server-side)
3. **Token Delivery**: Set as a **non-HttpOnly** cookie (`csrf_token`) so JavaScript can read it
4. **Token Validation**: On every POST/PUT/DELETE/PATCH request, the server compares the `X-CSRF-Token` header against the session's stored token
5. **Comparison**: Uses `secrets.compare_digest()` for constant-time comparison (prevents timing attacks)

### Why This Works

- An attacker on `evil.com` can trigger a cross-site POST to our API, and the browser will include `session_id` (cookie) automatically
- But the attacker **cannot read** the `csrf_token` cookie (different origin, SameSite=Strict)
- Therefore the attacker cannot set the `X-CSRF-Token` header
- The server rejects the request with 403

### Defense Layers

| Layer | How |
|-------|-----|
| **SameSite=Strict cookies** | Browser won't send session cookie on cross-origin requests |
| **X-CSRF-Token header** | Even if cookie leaks, attacker can't forge the custom header |
| **Constant-time comparison** | Prevents timing side-channel attacks |
| **Per-session token** | Token rotates with session rotation |

---

## Backend Implementation

### Schema Change (`core/db.py`)

```sql
-- sessions table: new column
csrf_token TEXT NOT NULL DEFAULT ''
```

ALTER TABLE migration for existing databases.

### CSRF Token Generation (`core/db.py`)

```python
def generate_csrf_token():
    return secrets.token_hex(32)  # 256-bit token
```

### Global Middleware (`app.py` — `before_request`)

A `@app.before_request` hook intercepts **all** incoming requests:

1. **Skip safe methods**: GET, HEAD, OPTIONS pass through
2. **Skip exempt paths**: `/api/v1/auth/*` — these are pre-authentication (login, register, etc.)
3. **Check header**: If `X-CSRF-Token` is missing → 403 "Missing CSRF token"
4. **Validate**: Compare header value against `sessions.csrf_token` — if mismatch → 403 "Invalid CSRF token"
5. **Legacy grace**: Sessions without a CSRF token (created before this feature) are allowed through

#### Exempt Endpoints

| Path Prefix | Reason |
|-------------|--------|
| `/api/v1/auth/` | Session doesn't exist yet (login/register/logout) |

All other state-changing endpoints are automatically protected.

### Token Lifecycle

| Event | Action |
|-------|--------|
| **Login** (`/auth/login/verify`) | Generate token → store in session → set `csrf_token` cookie |
| **Session Rotate** (`/auth/session/rotate`) | Generate new token → store in new session → update cookie |
| **Logout** (`/auth/logout`) | Clear `csrf_token` cookie |

### Cookie Properties

```python
resp.set_cookie('csrf_token', csrf_token,
    httponly=False,    # JavaScript MUST be able to read this
    secure=True,       # Only sent over HTTPS
    samesite='Strict', # Not sent on cross-origin requests
    max_age=1800       # Matches session expiry
)
```

---

## Frontend Implementation

### Global Fetch Wrapper (`frontend/js/script.js`)

An IIFE (Immediately Invoked Function Expression) overrides `window.fetch` to automatically inject the CSRF token:

```javascript
(function() {
    const originalFetch = window.fetch;
    window.fetch = function(url, options = {}) {
        const method = (options.method || 'GET').toUpperCase();
        if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
            const csrfToken = getCookie('csrf_token');
            if (csrfToken) {
                options.headers['X-CSRF-Token'] = csrfToken;
            }
        }
        return originalFetch.call(this, url, options);
    };
})();
```

**Key design decision**: By overriding `fetch` globally, every existing `fetch` call in the entire frontend automatically includes CSRF protection — zero changes to any page-specific JavaScript.

Handles both `Headers` objects and plain objects for compatibility.

---

## Files Changed

| File | Change |
|------|--------|
| `backend/api/core/db.py` | Added `csrf_token` to sessions; `generate_csrf_token()` function; `require_csrf` decorator (available for per-route use) |
| `backend/api/routes/auth.py` | Token generated on login + rotation; `csrf_token` cookie set/cleared |
| `backend/api/app.py` | Global `before_request` CSRF middleware; auth endpoints exempted |
| `frontend/js/script.js` | Global `fetch` override auto-injects `X-CSRF-Token` header |

---

## Security Considerations

1. **Token Entropy**: 256-bit tokens (`secrets.token_hex(32)`) are cryptographically secure and infeasible to brute-force.
2. **Double Submit Defense**: Even if `SameSite=Strict` is bypassed by a browser bug, the `X-CSRF-Token` header provides a second layer.
3. **No CORS Leakage**: The CORS policy restricts origins to `localhost:8000` and `localhost` (HTTPS), preventing cross-origin reads.
4. **FormData Uploads**: Resume uploads via `FormData` also go through the global `fetch` wrapper, so they include the CSRF token automatically.
