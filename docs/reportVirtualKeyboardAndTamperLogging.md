# Implementation Report: OTP Virtual Keyboard & Tamper-Evident Logging

## Overview

This report documents the implementation of two security mandates from the CSE 345/545 April milestone:

1. **OTP Virtual Keyboard** — Randomized on-screen keyboard for anti-keylogger OTP entry, linked to high-risk actions
2. **Tamper-Evident Logging** — SHA-256 hash-chained audit logs with chain verification endpoint

---

## 1. OTP Virtual Keyboard

### Component Design

The virtual keyboard is implemented as a self-contained JavaScript module (`frontend/js/virtual-keyboard.js`) using an IIFE pattern exposing a `VirtualKeyboard` API:

```js
VirtualKeyboard.show({
    title: 'Enter OTP',
    subtitle: 'Use the virtual keyboard',
    digits: 6,
    onSubmit: async (code) => { /* verify and return true/false */ },
    onCancel: () => { /* optional cleanup */ }
});
```

### Security Features

| Feature | Implementation |
|---------|---------------|
| **Randomized layout** | All 10 digit buttons are shuffled on every `show()` call using Fisher-Yates shuffle |
| **Anti-keylogger** | Physical keyboard input is blocked (`keydown` event intercepted and prevented on overlay) |
| **Anti-shoulder-surfing** | Entered digits are displayed as `●` bullets, not actual numbers |
| **Isolation** | Full-screen overlay with backdrop blur prevents interaction with underlying page |
| **Visual feedback** | Active digit box pulses, filled boxes glow, submit/delete buttons are color-coded |

### UI Design

- Glassmorphism container with gradient background
- 3×4 button grid (9 random digits + DEL / last digit / OK)
- Security badge: "Randomized layout • Anti-keylogger protection"
- Smooth entry animation (fade in)
- Button press animation (scale down on active)

### Backend OTP Verification Endpoint

**`POST /api/v1/admin/otp/verify`** (in `routes/admin.py`)

Verifies a TOTP code against the user's stored MFA secret. This is a general-purpose endpoint used by the frontend before allowing sensitive operations.

Request:
```json
{"totp_code": "123456", "action": "resume_download"}
```

Response (success):
```json
{"status": "success", "message": "OTP verified", "action": "resume_download"}
```

The endpoint:
- Requires authentication (session cookie)
- Decrypts the user's Fernet-encrypted MFA secret
- Uses `pyotp.TOTP.verify()` with `valid_window=1` (allows ±30 seconds)
- Logs both success and failure events to audit trail

### High-Risk Actions Linked (2 required, 2 implemented)

#### Action 1: Resume Download (profile.html)

The `downloadResume()` function now:
1. Opens the virtual keyboard overlay instead of directly downloading
2. User enters their TOTP code via randomized on-screen buttons
3. Frontend calls `POST /api/v1/admin/otp/verify` with `action: "resume_download"`
4. Only on success does `window.open()` trigger the actual download
5. On failure, the virtual keyboard shows "Invalid code. Try again." and clears input

#### Action 2: Password Change (profile.html)

A new "Change Password" widget was added to the profile sidebar:
1. User enters current password and new password in form fields
2. Clicks "Change (OTP Required)" button
3. Virtual keyboard overlay opens for TOTP verification
4. On OTP success, the password change request is sent to `PUT /api/v1/users/me/password`
5. Status feedback shown: green "✓ Password changed successfully!" or red error

#### Bonus: Login OTP (auth.html)

The login step 2 OTP entry now uses the virtual keyboard:
- OTP input fields are set to `readonly` — only the virtual keyboard can fill them
- A green "Enter OTP via Virtual Keyboard" button opens the keyboard
- Successful entry auto-fills the display boxes and submits login

---

## 2. Tamper-Evident Logging (Hash Chaining)

### Schema Changes (`core/db.py`)

Two columns added to `audit_logs`:

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `prev_hash` | TEXT | `''` | Hash of the previous log entry (or `'GENESIS'` for the first entry) |
| `log_hash` | TEXT | `''` | SHA-256 hash of the current entry computed from the chain |

### Hash Computation

The `log_action()` function now:
1. Fetches the most recent log entry's `log_hash` (or uses `'GENESIS'` if no entries exist)
2. Constructs a chain input string: `{prev_hash}|{email}|{event}|{timestamp}|{ip_address}`
3. Computes: `log_hash = SHA-256(chain_input)`
4. Stores both `prev_hash` and `log_hash` in the new row

```
Entry N:   prev_hash = log_hash(N-1)
           log_hash = SHA-256(prev_hash | email | event | timestamp | ip)

Entry N+1: prev_hash = log_hash(N)
           log_hash = SHA-256(prev_hash | email | event | timestamp | ip)
```

This creates an immutable chain where modifying any field in any entry would cause all subsequent hashes to mismatch.

### Chain Verification Endpoint

**`GET /api/v1/admin/audit/verify`** (admin-only)

Walks the entire `audit_logs` table in insertion order and:
1. For each entry, verifies that `prev_hash` matches the `log_hash` of the previous entry
2. Recomputes the `log_hash` from the stored fields and compares to the stored hash
3. Reports any broken links

Response (clean):
```json
{
    "status": "success",
    "chain_valid": true,
    "total_entries": 150,
    "broken_links": [],
    "message": "Chain integrity verified — no tampering detected"
}
```

Response (tampered):
```json
{
    "status": "success",
    "chain_valid": false,
    "total_entries": 150,
    "broken_links": [
        {
            "log_id": 42,
            "position": 42,
            "error": "log_hash does not match recomputed hash",
            "expected_hash": "a1b2c3d4e5f67890...",
            "actual_hash": "ffffffffffffffff..."
        }
    ],
    "message": "Chain broken at 1 point(s) — possible tampering"
}
```

### Legacy Entry Handling

Entries created before hash chaining was implemented will have empty `prev_hash` and `log_hash` values. The verification endpoint detects these as a break between legacy and new entries, which is expected behavior during the migration period.

---

## Files Changed

| File | Change |
|------|--------|
| `frontend/js/virtual-keyboard.js` | **NEW** — Reusable virtual keyboard component |
| `backend/api/core/db.py` | Added `prev_hash`, `log_hash` to `audit_logs`; refactored `log_action()` for hash chaining; ALTER TABLE migration |
| `backend/api/routes/admin.py` | Added `GET /audit/verify` (chain verification) and `POST /otp/verify` (OTP verification for high-risk actions) |
| `frontend/public/auth.html` | Login OTP now uses virtual keyboard; password trigger linked |
| `frontend/public/profile.html` | Resume download gated by OTP; password change widget with OTP gate; virtual-keyboard.js included |

---

## Security Considerations

1. **Virtual Keyboard Limitations**: While effective against software keyloggers, the virtual keyboard does not protect against screen-capture malware or physical shoulder surfing at close range.
2. **Hash Chain Gaps**: If the database is truncated (DELETE operations), the chain will appear broken from the deletion point. This is by design — an admin should never delete audit logs.
3. **OTP Window**: The verification uses `valid_window=1`, allowing codes from the previous and next 30-second windows. This balances security with usability.
4. **TOTP Secret Decryption**: The OTP verify endpoint attempts to decrypt the MFA secret using Fernet. If the secret format changes, a fallback to raw secret is used.
