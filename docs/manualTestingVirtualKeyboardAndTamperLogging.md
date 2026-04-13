# Manual Testing Guide: OTP Virtual Keyboard & Tamper-Evident Logging

> **Prerequisites**: Server running (`python3 backend/api/app.py`), at least 1 registered user with TOTP set up, authenticator app ready.

---

## Table of Contents

1. [Virtual Keyboard — Login OTP](#1-virtual-keyboard--login-otp)
2. [Virtual Keyboard — Resume Download](#2-virtual-keyboard--resume-download)
3. [Virtual Keyboard — Password Change](#3-virtual-keyboard--password-change)
4. [Tamper-Evident Logging — Hash Chain](#4-tamper-evident-logging--hash-chain)
5. [Tamper-Evident Logging — Tamper Detection](#5-tamper-evident-logging--tamper-detection)
6. [Negative Tests](#6-negative-tests)

---

## 1. Virtual Keyboard — Login OTP

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1.1 | Navigate to `auth.html`, enter credentials, click Continue | Step 2 OTP screen appears |
| 1.2 | OTP input boxes are `readonly` | Cannot type with physical keyboard |
| 1.3 | Click **"Enter OTP via Virtual Keyboard"** (green button) | Virtual keyboard overlay appears |
| 1.4 | Observe the digit buttons (0–9) | Buttons are **randomly arranged** — different from standard numpad |
| 1.5 | Close and reopen the keyboard | Layout is **different on each open** (randomized) |
| 1.6 | Enter your 6-digit TOTP code via the on-screen buttons | Each digit appears as `●` in the display boxes |
| 1.7 | Press the red **DEL** button | Last digit is removed |
| 1.8 | Complete 6 digits and press green **OK** | "Verifying..." appears, then login succeeds + redirect |
| 1.9 | Enter a wrong code and press OK | "Invalid code. Try again." shown, digits cleared |
| 1.10 | Observe the footer badge | "Randomized layout • Anti-keylogger protection" shown |

---

## 2. Virtual Keyboard — Resume Download

*Prerequisite: At least 1 resume uploaded.*

| Step | Action | Expected Result |
|------|--------|-----------------|
| 2.1 | Navigate to `profile.html` | Resumes list visible |
| 2.2 | Click the **download button** (⬇) on a resume | Virtual keyboard overlay appears (NOT a direct download) |
| 2.3 | Title reads "Verify Identity for Download" | Correct context |
| 2.4 | Enter valid TOTP code via virtual keyboard | "✓ Verified" shown, then download starts in new tab |
| 2.5 | Enter invalid TOTP code | "Invalid code. Try again." — no download occurs |
| 2.6 | Press **Cancel** | Overlay closes, no download |

### API Verification

```bash
# Direct OTP verification
curl -s -X POST http://localhost:8000/api/v1/admin/otp/verify \
  -H "Content-Type: application/json" \
  --cookie "session_id=<SESSION>" \
  -d '{"totp_code": "123456", "action": "resume_download"}' | python3 -m json.tool

# Expected (valid OTP):
# {"status": "success", "message": "OTP verified", "action": "resume_download"}

# Expected (invalid OTP):
# {"status": "error", "message": "Invalid OTP code"}
```

---

## 3. Virtual Keyboard — Password Change

| Step | Action | Expected Result |
|------|--------|-----------------|
| 3.1 | Navigate to `profile.html` | Right sidebar shows "Change Password" section |
| 3.2 | Enter current password and new password | Fields populated |
| 3.3 | Click **"Change (OTP Required)"** | Virtual keyboard overlay appears |
| 3.4 | Title reads "Verify Identity for Password Change" | Correct context |
| 3.5 | Enter valid TOTP code | "✓ Password changed successfully!" appears in green |
| 3.6 | Password fields are cleared | Clean state after success |
| 3.7 | Try logging out and back in with the new password | Login succeeds |
| 3.8 | Enter invalid TOTP code | "Invalid OTP." appears in red — password NOT changed |
| 3.9 | Leave password fields empty and click Change | "Both fields are required." error shown (no keyboard opens) |
| 3.10 | Enter new password shorter than 8 chars | "New password must be at least 8 characters." error |

---

## 4. Tamper-Evident Logging — Hash Chain

### 4a. Verify Hash Chain Integrity

*Prerequisite: Admin user (set `role='admin'` in DB for a user).*

| Step | Action | Expected Result |
|------|--------|-----------------|
| 4.1 | Log in as admin | Session established |
| 4.2 | Perform several actions (upload resume, send message, etc.) | Audit events generated |

```bash
# Verify the chain
curl -s http://localhost:8000/api/v1/admin/audit/verify \
  --cookie "session_id=<ADMIN_SESSION>" | python3 -m json.tool

# Expected (for new entries):
# {
#   "status": "success",
#   "chain_valid": true,   (or false if legacy entries exist)
#   "total_entries": 50,
#   "broken_links": [...],
#   "message": "Chain integrity verified — no tampering detected"
# }
```

### 4b. Inspect Individual Log Entries

```bash
# View recent audit logs via admin dashboard
curl -s http://localhost:8000/api/v1/admin/dashboard \
  --cookie "session_id=<ADMIN_SESSION>" | python3 -m json.tool | head -60

# Each audit_log entry now includes:
# - prev_hash: hash of the previous entry (or "GENESIS" for first)
# - log_hash: SHA-256 computed from (prev_hash|email|event|timestamp|ip)
```

### 4c. Verify Chain Linkage

| Step | Action | Expected Result |
|------|--------|-----------------|
| 4.3 | Run: `sqlite3 backend/data/secure_app.db "SELECT id, prev_hash, log_hash FROM audit_logs ORDER BY id DESC LIMIT 5;"` | Each entry's `prev_hash` matches the previous entry's `log_hash` |
| 4.4 | The first new entry has `prev_hash = 'GENESIS'` | Genesis block marker |

---

## 5. Tamper-Evident Logging — Tamper Detection

### 5a. Tamper with an Audit Log Entry

| Step | Action | Expected Result |
|------|--------|-----------------|
| 5.1 | Note the ID of a recent audit log entry | |
| 5.2 | Modify the event field in the database: | |

```bash
sqlite3 backend/data/secure_app.db "UPDATE audit_logs SET event='TAMPERED_EVENT' WHERE id=<LOG_ID>;"
```

| Step | Action | Expected Result |
|------|--------|-----------------|
| 5.3 | Call `GET /api/v1/admin/audit/verify` | Response shows `chain_valid: false` |
| 5.4 | `broken_links` array contains the tampered entry | `error: "log_hash does not match recomputed hash"` |

### 5b. Restore the Entry

```bash
# Re-run the verify endpoint to confirm the break is fixed
# (You'd need to recompute the correct hash — or delete and re-insert)
```

### 5c. Delete an Entry from the Middle

| Step | Action | Expected Result |
|------|--------|-----------------|
| 5.5 | Delete a middle entry: `sqlite3 backend/data/secure_app.db "DELETE FROM audit_logs WHERE id=<MID_ID>;"` | |
| 5.6 | Call verify endpoint | `chain_valid: false` — the entry after the deleted one has a `prev_hash` that no longer matches |

---

## 6. Negative Tests

| Step | Action | Expected Result |
|------|--------|-----------------|
| 6.1 | Call `/api/v1/admin/otp/verify` without a session | 401 Unauthorized |
| 6.2 | Submit OTP with less than 6 digits | "A 6-digit OTP code is required" (400) |
| 6.3 | Submit empty `totp_code` | "A 6-digit OTP code is required" (400) |
| 6.4 | Non-admin calls `/api/v1/admin/audit/verify` | "Forbidden. Admins only." (403) |
| 6.5 | Check audit trail for OTP events | `OTP_VERIFICATION_SUCCESS` and `OTP_VERIFICATION_FAILED` logged |
| 6.6 | Check audit trail for chain verification | `AUDIT_CHAIN_VERIFIED: valid=true/false, entries=N, breaks=M` logged |

---

## Quick Verification Checklist

### Virtual Keyboard
- [ ] Login OTP input fields are readonly (physical keyboard blocked)
- [ ] Virtual keyboard button layout is randomized on each open
- [ ] Digits display as `●` bullets (anti-shoulder-surfing)
- [ ] Resume download requires OTP via virtual keyboard
- [ ] Password change requires OTP via virtual keyboard
- [ ] Invalid OTP codes are rejected gracefully
- [ ] Cancel button closes overlay without action

### Tamper-Evident Logging
- [ ] New audit log entries have `prev_hash` and `log_hash` populated
- [ ] First new entry has `prev_hash = 'GENESIS'`
- [ ] Each entry's `prev_hash` matches previous entry's `log_hash`
- [ ] `/api/v1/admin/audit/verify` returns `chain_valid: true` for clean chain
- [ ] Modifying any field causes verification to fail
- [ ] Deleting an entry causes verification to fail
- [ ] Verification result is itself logged to the audit trail
