# Manual Testing Guide: PKI Integration

> **Prerequisites**: Server running (`python3 backend/api/app.py`), at least 2 registered users with TOTP set up, `cryptography` package installed (`pip3 install cryptography`).

---

## Table of Contents

1. [Resume Digital Signatures (Function 1)](#1-resume-digital-signatures-function-1)
2. [Message Signing — Non-Repudiation (Function 2)](#2-message-signing--non-repudiation-function-2)
3. [PKI Key Management](#3-pki-key-management)
4. [Tamper Detection Tests](#4-tamper-detection-tests)
5. [Negative Tests](#5-negative-tests)

---

## 1. Resume Digital Signatures (Function 1)

### 1a. Upload with Automatic Signing

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1.1 | Log in as any user | Session established |
| 1.2 | Upload a PDF resume via `profile.html` or API | Upload succeeds |
| 1.3 | Check the API response | `"pki_signed": true` in response |
| 1.4 | List resumes via `GET /api/v1/users/resumes` | Each resume has `"is_signed": true` |

```bash
# Upload a resume
curl -s -X POST http://localhost:8000/api/v1/users/resumes \
  --cookie "session_id=<SESSION>" \
  -F "resume=@test_resume.pdf" | python3 -m json.tool

# Expected:
# {"status": "success", "resume_id": "...", "pki_signed": true}
```

### 1b. Download with Automatic Verification

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1.5 | Download the resume via `GET /api/v1/users/resumes/<id>/download` | PDF file downloads correctly |
| 1.6 | Check response headers in browser DevTools (Network tab) | `X-PKI-Signature-Status: valid` and `X-PKI-Signer: <email>` |

```bash
# Download and check headers
curl -sI http://localhost:8000/api/v1/users/resumes/<RESUME_ID>/download \
  --cookie "session_id=<SESSION>"

# Expected headers include:
# X-PKI-Signature-Status: valid
# X-PKI-Signer: user@test.com
```

### 1c. Explicit Signature Verification

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1.7 | Call `GET /api/v1/users/resumes/<id>/verify` | Returns verification result |

```bash
curl -s http://localhost:8000/api/v1/users/resumes/<RESUME_ID>/verify \
  --cookie "session_id=<SESSION>" | python3 -m json.tool

# Expected:
# {
#   "status": "success",
#   "verified": true,
#   "reason": "Signature is valid",
#   "signer": "user@test.com",
#   "signature_algorithm": "RSA-2048-PSS-SHA256"
# }
```

---

## 2. Message Signing — Non-Repudiation (Function 2)

### 2a. Send Signed Message

| Step | Action | Expected Result |
|------|--------|-----------------|
| 2.1 | Open `messages.html`, select a conversation | Chat opens |
| 2.2 | Type and send a message | Message appears in chat |
| 2.3 | Check browser DevTools → Network → the POST request response | `"pki_signed": true` in JSON response |

```bash
# Send a message via API
curl -s -X POST http://localhost:8000/api/v1/messages/conversations/<CONV_ID>/messages \
  -H "Content-Type: application/json" \
  --cookie "session_id=<SESSION>" \
  -d '{"encrypted_content": "base64ciphertext==", "iv": "base64iv=="}' | python3 -m json.tool

# Expected:
# {"status": "success", "message_id": 1, "timestamp": "...", "pki_signed": true}
```

### 2b. Retrieve Messages with Signatures

| Step | Action | Expected Result |
|------|--------|-----------------|
| 2.4 | Call `GET /api/v1/messages/conversations/<id>/messages` | Each message includes `signature` field |
| 2.5 | Verify `pki_enabled: true` in response | PKI integration confirmed |

```bash
curl -s http://localhost:8000/api/v1/messages/conversations/<CONV_ID>/messages \
  --cookie "session_id=<SESSION>" | python3 -m json.tool

# Expected: Each message object has a "signature" field (base64 string)
# Response includes "pki_enabled": true
```

### 2c. Verify Specific Message Signature

| Step | Action | Expected Result |
|------|--------|-----------------|
| 2.6 | Call `GET /api/v1/messages/messages/<msg_id>/verify` | Verification result returned |

```bash
curl -s http://localhost:8000/api/v1/messages/messages/1/verify \
  --cookie "session_id=<SESSION>" | python3 -m json.tool

# Expected:
# {
#   "status": "success",
#   "verified": true,
#   "reason": "Signature is valid",
#   "sender": "user@test.com",
#   "message_id": 1,
#   "signature_algorithm": "RSA-2048-PSS-SHA256"
# }
```

---

## 3. PKI Key Management

### 3a. View Your Public Key

| Step | Action | Expected Result |
|------|--------|-----------------|
| 3.1 | Call `GET /api/v1/users/me/pki` | Returns your RSA public key in PEM format |

```bash
curl -s http://localhost:8000/api/v1/users/me/pki \
  --cookie "session_id=<SESSION>" | python3 -m json.tool

# Expected:
# {
#   "status": "success",
#   "email": "user@test.com",
#   "public_key": "-----BEGIN PUBLIC KEY-----\nMIIBI...",
#   "algorithm": "RSA-2048"
# }
```

### 3b. Lazy Key Generation

| Step | Action | Expected Result |
|------|--------|-----------------|
| 3.2 | Register a brand new user | User has no PKI keys yet |
| 3.3 | Upload a resume or send a message | PKI keys auto-generated on first use |
| 3.4 | Check DB: `sqlite3 backend/data/secure_app.db "SELECT pki_public_key FROM users WHERE email='newuser@test.com';"` | PEM public key stored |

### 3c. Verify Key Persistence

| Step | Action | Expected Result |
|------|--------|-----------------|
| 3.5 | Upload a second resume | Same key pair used (signature verifiable with same public key) |
| 3.6 | Send multiple messages | All signed with the same private key |

---

## 4. Tamper Detection Tests

### 4a. Resume Tampering (Database Level)

| Step | Action | Expected Result |
|------|--------|-----------------|
| 4.1 | Upload a resume and note the `resume_id` | Upload succeeds |
| 4.2 | Modify the stored file hash in DB: | |

```bash
sqlite3 backend/data/secure_app.db "UPDATE resumes SET file_hash='tampered_hash' WHERE resume_id='<RESUME_ID>';"
```

| Step | Action | Expected Result |
|------|--------|-----------------|
| 4.3 | Call `GET /api/v1/users/resumes/<id>/verify` | `"verified": false, "reason": "Signature verification failed — data may have been tampered with"` |
| 4.4 | Restore the hash or re-upload | Verification passes again |

### 4b. Message Tampering (Database Level)

| Step | Action | Expected Result |
|------|--------|-----------------|
| 4.5 | Send a message and note the `message_id` | Message sent |
| 4.6 | Modify the encrypted_content in DB: | |

```bash
sqlite3 backend/data/secure_app.db "UPDATE messages SET encrypted_content='tampered_content' WHERE id=<MSG_ID>;"
```

| Step | Action | Expected Result |
|------|--------|-----------------|
| 4.7 | Call `GET /api/v1/messages/messages/<msg_id>/verify` | `"verified": false, "reason": "Signature verification failed — data may have been tampered with"` |

---

## 5. Negative Tests

| Step | Action | Expected Result |
|------|--------|-----------------|
| 5.1 | Verify a non-existent resume: `GET /api/v1/users/resumes/fake-id/verify` | `"Resume not found"` (404) |
| 5.2 | Verify a non-existent message: `GET /api/v1/messages/messages/99999/verify` | `"Message not found"` (404) |
| 5.3 | Verify a message from a conversation you're not in | `"Not a member of this conversation"` (403) |
| 5.4 | Check audit log for PKI actions | Events `RESUME_UPLOADED_AND_SIGNED` and `MESSAGE_SENT_AND_SIGNED` appear |

---

## Quick Verification Checklist

- [ ] Resume upload returns `pki_signed: true`
- [ ] Resume download headers include `X-PKI-Signature-Status: valid`
- [ ] Resume verify endpoint returns `verified: true`
- [ ] Message send returns `pki_signed: true`
- [ ] Message objects contain `signature` field
- [ ] Message verify endpoint returns `verified: true`
- [ ] Tampering with resume hash causes verification failure
- [ ] Tampering with message content causes verification failure
- [ ] PKI keys are lazily generated on first use
- [ ] Public key is retrievable via `/me/pki`
