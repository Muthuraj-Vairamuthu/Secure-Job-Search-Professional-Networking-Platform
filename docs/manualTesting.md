# Manual Testing Guide — Secure Job Search & Professional Networking Platform

**FCS GROUP 19 — CSE 345/545**

> **Prerequisites**
> - Python 3.10+ with dependencies installed (`pip install -r requirements.txt`)
> - An authenticator app (Google Authenticator, Authy, or any TOTP app)
> - A modern browser (Chrome/Firefox recommended)
> - `curl` or Postman for API-level tests
> - The server running: `cd backend/api && python3 app.py` (runs on `http://localhost:8000`)

---

## Table of Contents

1. [Setup & First Launch](#1-setup--first-launch)
2. [User Registration (with MFA)](#2-user-registration-with-mfa)
3. [User Login (with MFA)](#3-user-login-with-mfa)
4. [Profile Management](#4-profile-management)
5. [Secure Resume Upload & Download](#5-secure-resume-upload--download)
6. [Company Pages (Recruiter)](#6-company-pages-recruiter)
7. [Job Postings (Recruiter)](#7-job-postings-recruiter)
8. [Job Search & Application (Job Seeker)](#8-job-search--application-job-seeker)
9. [Application Tracking & Status Updates](#9-application-tracking--status-updates)
10. [Secure Messaging (E2EE)](#10-secure-messaging-e2ee)
11. [Admin Dashboard](#11-admin-dashboard)
12. [Security Verification Tests](#12-security-verification-tests)
13. [Logout & Session Expiry](#13-logout--session-expiry)

---

## 1. Setup & First Launch

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1.1 | Run `pip install -r requirements.txt` | All dependencies install without errors |
| 1.2 | Run `python3 backend/api/app.py` | Server starts on port 8000, no errors in terminal |
| 1.3 | Open `http://localhost:8000` in browser | Landing page loads with "FCS GROUP 19" branding |
| 1.4 | Navigate to `http://localhost:8000/auth.html` | Login/Signup page is displayed |

---

## 2. User Registration (with MFA)

### 2a. Register a Job Seeker

| Step | Action | Expected Result |
|------|--------|-----------------|
| 2.1 | On `auth.html`, click **"Sign Up"** | Signup form appears (Step 1 of 2) |
| 2.2 | Fill in: Name=`Test User`, Email=`user@test.com`, Role=`Job Seeker`, Password=`TestSecure123!` | Fields accept input |
| 2.3 | Click **"Continue Setup"** | Step 2 appears, showing a TOTP setup key |
| 2.4 | Copy the displayed secret key and add it to your authenticator app | Authenticator app starts generating 6-digit codes |
| 2.5 | Enter the current 6-digit code from the authenticator | "Registration complete! You can now log in." alert appears |

### 2b. Register a Recruiter

| Step | Action | Expected Result |
|------|--------|-----------------|
| 2.6 | Repeat steps 2.1–2.5 but with Email=`recruiter@test.com`, Role=`Recruiter / Employer` | Registration succeeds |

### 2c. Register an Admin (via API)

Since the frontend only offers "Job Seeker" and "Recruiter" roles, admin accounts are created via API:

```bash
# Step 1: Register
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@test.com","password":"AdminSecure123!","role":"admin","name":"Admin User"}' | python3 -m json.tool

# Note the "mfa_secret_setup_key" from the response
# Add it to your authenticator app, then:

# Step 2: Verify (replace CONTEXT with the full context object from Step 1, CODE with your TOTP code)
curl -s -X POST http://localhost:8000/api/v1/auth/register/verify \
  -H "Content-Type: application/json" \
  -d '{"context": <PASTE_CONTEXT_HERE>, "totp_code": "<CODE>"}' | python3 -m json.tool
```

### 2d. Negative Tests

| Step | Action | Expected Result |
|------|--------|-----------------|
| 2.7 | Try registering with a weak password (e.g., `password`) | "Invalid input format or password policy not met" error |
| 2.8 | Try registering with the same email again | "User already exists" error |
| 2.9 | Enter a wrong TOTP code during Step 2 | "Invalid TOTP Code. Account creation aborted." error |

---

## 3. User Login (with MFA)

### 3a. Successful Login

| Step | Action | Expected Result |
|------|--------|-----------------|
| 3.1 | On `auth.html`, enter `user@test.com` and `TestSecure123!` | Click "Continue" |
| 3.2 | Step 2 appears — OTP input boxes | 6 individual digit input boxes displayed |
| 3.3 | Enter correct TOTP code from authenticator | Redirects to `dashboard.html` |

### 3b. Negative Tests

| Step | Action | Expected Result |
|------|--------|-----------------|
| 3.4 | Enter wrong password | "Invalid credentials" alert |
| 3.5 | Enter wrong TOTP code | "Invalid OTP code." alert |
| 3.6 | Try the same TOTP code again within 30s | "OTP has already been used. Wait for a new code." |
| 3.7 | Fail 5+ times consecutively | Account locks for 5 minutes; "Account locked due to multiple failed attempts" |

---

## 4. Profile Management

*Prerequisite: Logged in as any user.*

| Step | Action | Expected Result |
|------|--------|-----------------|
| 4.1 | Navigate to `profile.html` | Profile page loads with your name, email, role badge |
| 4.2 | Click **"Edit Profile"** | Redirects to `edit_profile.html` |
| 4.3 | Change your headline to `Security Researcher` and save | Success message |
| 4.4 | Return to `profile.html` | Updated headline is displayed |
| 4.5 | Update bio, location via the edit page | Fields persist correctly |

### API Verification

```bash
# Get profile (use browser cookies or session)
curl -s http://localhost:8000/api/v1/users/me \
  --cookie "session_id=<YOUR_SESSION_COOKIE>" | python3 -m json.tool
```

---

## 5. Secure Resume Upload & Download

*Prerequisite: Logged in as any user.*

### 5a. Upload

| Step | Action | Expected Result |
|------|--------|-----------------|
| 5.1 | On `profile.html`, click **"Add Resume"** | File picker opens |
| 5.2 | Select a valid PDF file (< 5MB) | "Resume uploaded securely!" alert. Resume appears in list. |
| 5.3 | Check the stored file on disk: `backend/data/.secure_storage/resumes/` | File is a `.enc` binary blob (encrypted), NOT readable as PDF |
| 5.4 | Check `backend/data/.secure_storage/keys/` | Corresponding `.enc.key` file exists |

### 5b. Download

| Step | Action | Expected Result |
|------|--------|-----------------|
| 5.5 | Click the **download button** (⬇) next to your resume on `profile.html` | PDF file downloads correctly, readable in a PDF viewer |
| 5.6 | Check response headers (in browser DevTools → Network tab) | `Content-Disposition: attachment`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff` |

### 5c. Delete

| Step | Action | Expected Result |
|------|--------|-----------------|
| 5.7 | Click the **delete button** (🗑) next to a resume | Confirmation prompt → resume removed from list |
| 5.8 | Verify on disk: the `.enc` and `.key` files are deleted | Files no longer present in secure_storage directories |

### 5d. Negative Tests

| Step | Action | Expected Result |
|------|--------|-----------------|
| 5.9 | Try uploading a `.exe` file renamed to `.pdf` | "File content does not match the declared extension" error |
| 5.10 | Try uploading a file > 5MB | "File exceeds the 5 MB size limit" error |
| 5.11 | Try uploading `resume.pdf.exe` | "Suspicious filename: multiple extensions detected" error |

---

## 6. Company Pages (Recruiter)

*Prerequisite: Logged in as `recruiter@test.com` (role=recruiter).*

| Step | Action | Expected Result |
|------|--------|-----------------|
| 6.1 | Navigate to `company.html` | Company management page loads |
| 6.2 | Create a company with Name=`SecureTech Inc`, Description, Location, Website | "Company created" success message |
| 6.3 | View the company list | New company appears with 0 jobs |
| 6.4 | Update company description | "Company updated" confirmation |

### API Verification

```bash
# List all companies
curl -s http://localhost:8000/api/v1/companies \
  --cookie "session_id=<SESSION>" | python3 -m json.tool

# Get your companies
curl -s http://localhost:8000/api/v1/companies/me \
  --cookie "session_id=<SESSION>" | python3 -m json.tool
```

### Negative Tests

| Step | Action | Expected Result |
|------|--------|-----------------|
| 6.5 | Log in as `user@test.com` (job seeker) and try `POST /api/v1/companies` | "Forbidden. Recruiters only." (403) |
| 6.6 | Try updating a company you don't own | "Permission denied" (403) |

---

## 7. Job Postings (Recruiter)

*Prerequisite: Logged in as recruiter with at least one company created.*

| Step | Action | Expected Result |
|------|--------|-----------------|
| 7.1 | Navigate to `jobs.html` or `company.html` | Job posting interface loads |
| 7.2 | Create a job: Title=`Security Engineer`, skills=`Python, Cryptography`, location=`Remote`, type=`full-time` | "Job posted" success, job appears in listings |
| 7.3 | Update the job description | "Job updated" confirmation |
| 7.4 | Create a second job under the same company | Both jobs visible |

### API Verification

```bash
# List all active jobs
curl -s http://localhost:8000/api/v1/jobs \
  --cookie "session_id=<SESSION>" | python3 -m json.tool

# Search by keyword
curl -s "http://localhost:8000/api/v1/jobs?keyword=security" \
  --cookie "session_id=<SESSION>" | python3 -m json.tool

# Filter by type
curl -s "http://localhost:8000/api/v1/jobs?job_type=full-time" \
  --cookie "session_id=<SESSION>" | python3 -m json.tool
```

---

## 8. Job Search & Application (Job Seeker)

*Prerequisite: Logged in as `user@test.com`, at least one job posted by recruiter.*

| Step | Action | Expected Result |
|------|--------|-----------------|
| 8.1 | Navigate to `jobs.html` | Job listings load (search/filter UI visible) |
| 8.2 | Search for `Security` in the keyword box | Matching jobs displayed |
| 8.3 | Filter by location or job type | Results narrow correctly |
| 8.4 | Apply to a job (with resume and cover note) | "Application submitted" success |
| 8.5 | Try applying to the same job again | "You have already applied to this job" (409) |

### API Verification

```bash
# Apply to a job
curl -s -X POST http://localhost:8000/api/v1/applications \
  -H "Content-Type: application/json" \
  --cookie "session_id=<SESSION>" \
  -d '{"job_id": 1, "resume_id": "<YOUR_RESUME_ID>", "cover_note": "I am interested"}' | python3 -m json.tool
```

---

## 9. Application Tracking & Status Updates

### 9a. Job Seeker View

| Step | Action | Expected Result |
|------|--------|-----------------|
| 9.1 | As `user@test.com`, check `GET /api/v1/applications/me` | List of your applications with status, job title, company name |

### 9b. Recruiter View

| Step | Action | Expected Result |
|------|--------|-----------------|
| 9.2 | As `recruiter@test.com`, check `GET /api/v1/applications/job/<job_id>` | List of applicants with name, headline, status |
| 9.3 | Update an application status to `Reviewed` via `PUT /api/v1/applications/<app_id>/status` | "Application status updated to Reviewed" |
| 9.4 | Update to `Interviewed`, then `Offer` | Status changes correctly each time |

```bash
# Recruiter: View applicants for job 1
curl -s http://localhost:8000/api/v1/applications/job/1 \
  --cookie "session_id=<RECRUITER_SESSION>" | python3 -m json.tool

# Recruiter: Update status
curl -s -X PUT http://localhost:8000/api/v1/applications/1/status \
  -H "Content-Type: application/json" \
  --cookie "session_id=<RECRUITER_SESSION>" \
  -d '{"status": "Reviewed", "recruiter_notes": "Strong candidate"}' | python3 -m json.tool
```

### Negative Tests

| Step | Action | Expected Result |
|------|--------|-----------------|
| 9.5 | As job seeker, try updating an application status | "Forbidden. Recruiters only." (403) |
| 9.6 | As a different recruiter, try updating status of another recruiter's job | "Permission denied" (403) |
| 9.7 | Set status to `InvalidStatus` | "Invalid status" (400) |

---

## 10. Secure Messaging (E2EE)

*Prerequisite: At least two users registered and logged in (use two browser profiles/incognito).*

### 10a. Direct Message

| Step | Action | Expected Result |
|------|--------|-----------------|
| 10.1 | Navigate to `messages.html` | "End-to-End Encrypted Messaging" empty state shown |
| 10.2 | Click **+** button to create new conversation | "New Conversation" modal opens |
| 10.3 | Search for the other user's name or email | User appears in search results |
| 10.4 | Select user, click **"Start Conversation"** | Conversation created, chat opens |
| 10.5 | Type a message and press Enter or click Send | Message appears in chat bubble |
| 10.6 | In the other user's browser, open the same conversation | Message appears (decrypted) within ~3 seconds |
| 10.7 | Reply from the second user | Both users see both messages |

### 10b. Group Chat

| Step | Action | Expected Result |
|------|--------|-----------------|
| 10.8 | Click **+**, switch to **"Group"** tab | Group name field appears |
| 10.9 | Name the group, add 2+ participants | Group conversation created |
| 10.10 | Send messages in the group | All members can see messages |
| 10.11 | As creator, click the **add member** button and add another user | New member is added |

### 10c. Verify E2EE

| Step | Action | Expected Result |
|------|--------|-----------------|
| 10.12 | Open browser DevTools → Network tab | Observe POST payload to `/api/v1/messages/conversations/<id>/messages` |
| 10.13 | Inspect the request body | `encrypted_content` is base64 ciphertext, `iv` is base64 — **no plaintext** |
| 10.14 | Check the database: `sqlite3 backend/data/secure_app.db "SELECT encrypted_content FROM messages LIMIT 3;"` | Only ciphertext stored — no readable message text |

### 10d. Verify E2EE Lock Badge

| Step | Action | Expected Result |
|------|--------|-----------------|
| 10.15 | Look at conversation list | Each conversation shows 🔒 lock icon |
| 10.16 | Look at chat header | "End-to-End Encrypted" badge visible |

---

## 11. Admin Dashboard

*Prerequisite: Logged in as admin user (see Section 2c for admin registration).*

| Step | Action | Expected Result |
|------|--------|-----------------|
| 11.1 | Navigate to `admin.html` | Admin panel loads with stat cards |
| 11.2 | Check **Users tab** | All registered users listed with ID, email, name, role, MFA status, failed attempts |
| 11.3 | Check **Audit Log tab** | All login attempts, registrations, job actions visible with timestamps, IPs, and color-coded event badges |
| 11.4 | Check **Resumes tab** | All uploaded resumes with owner, type, size, visibility |
| 11.5 | Check **Companies tab** | All companies with owner, location, job count |
| 11.6 | Check **Jobs tab** | All job postings with status badge |
| 11.7 | Check **Applications tab** | All applications with status badges |
| 11.8 | Check **Sessions tab** | Active and expired sessions with timestamps |
| 11.9 | Click **"Refresh"** button | Data reloads |

### Negative Tests

| Step | Action | Expected Result |
|------|--------|-----------------|
| 11.10 | Log in as `user@test.com` (job seeker) and navigate to `admin.html` | Dashboard API returns "Forbidden. Admins only." (403); no data loads |
| 11.11 | Log in as `recruiter@test.com` and navigate to `admin.html` | Same 403 result |

---

## 12. Security Verification Tests

### 12a. SQL Injection

| Step | Action | Expected Result |
|------|--------|-----------------|
| 12.1 | Try logging in with email: `' OR 1=1 --` | "Invalid credentials" (not logged in) |
| 12.2 | Try searching jobs with keyword: `'; DROP TABLE jobs; --` | Normal empty results (no crash, no data loss) |
| 12.3 | Verify the `jobs` table still exists after the above | `sqlite3 backend/data/secure_app.db "SELECT COUNT(*) FROM jobs;"` returns normally |

### 12b. Password Security

| Step | Action | Expected Result |
|------|--------|-----------------|
| 12.4 | Check the database: `sqlite3 backend/data/secure_app.db "SELECT password_hash FROM users LIMIT 1;"` | Displays Argon2id hash (starts with `$argon2id$`), NOT plaintext |
| 12.5 | Check TOTP secrets: `SELECT mfa_secret FROM users LIMIT 1;` | Encrypted blob (Fernet token), NOT base32 plaintext |

### 12c. Session Security

| Step | Action | Expected Result |
|------|--------|-----------------|
| 12.6 | In browser DevTools → Application → Cookies → `session_id` | Cookie has `HttpOnly` ✅, `SameSite=Strict` ✅ |
| 12.7 | Copy the `session_id` cookie value | It is a random 86-char token |
| 12.8 | Check DB: `SELECT session_hash FROM sessions LIMIT 1;` | Stored as SHA-256 hash, NOT the raw token |

### 12d. Resume Encryption Verification

| Step | Action | Expected Result |
|------|--------|-----------------|
| 12.9 | Upload a PDF resume | Upload succeeds |
| 12.10 | Try to open the encrypted file directly: `cat backend/data/.secure_storage/resumes/<filename>.enc` | Unreadable binary data (ciphertext) |
| 12.11 | Check file permissions: `ls -la backend/data/.secure_storage/resumes/` | Files are `rw-------` (600) |
| 12.12 | Check key permissions: `ls -la backend/data/.secure_storage/keys/` | Files are `r--------` (400) |

### 12e. Rate Limiting

| Step | Action | Expected Result |
|------|--------|-----------------|
| 12.13 | Send 6 failed login attempts for the same account | After 5th: "Account locked due to multiple failed attempts" |
| 12.14 | Wait for the lock to expire and try with correct credentials | Login succeeds, `failed_attempts` reset to 0 |

### 12f. XSS Prevention

| Step | Action | Expected Result |
|------|--------|-----------------|
| 12.15 | Update your name to `<script>alert('xss')</script>` via profile edit | Name is stored as-is in DB |
| 12.16 | View your profile on `profile.html` | Script tag is rendered as text, NOT executed |
| 12.17 | Send a message containing `<img src=x onerror=alert('xss')>` | Message displays as text, no alert popup |

---

## 13. Logout & Session Expiry

| Step | Action | Expected Result |
|------|--------|-----------------|
| 13.1 | Click **"Logout"** on profile page | Redirects to `auth.html` |
| 13.2 | Try navigating back to `dashboard.html` | Redirected to `auth.html` (session gone) |
| 13.3 | Check cookies | `session_id` cookie is cleared |
| 13.4 | Check DB: `SELECT * FROM sessions WHERE user_id='...'` | Session row deleted |

---

## Quick Reference: Test Accounts

| Role | Email | Password | Notes |
|------|-------|----------|-------|
| Job Seeker | `user@test.com` | `TestSecure123!` | Register via UI |
| Recruiter | `recruiter@test.com` | `TestSecure123!` | Register via UI (select "Recruiter") |
| Admin | `admin@test.com` | `AdminSecure123!` | Register via API (see Section 2c) |

> ⚠️ **All accounts require TOTP setup.** Save the setup key in your authenticator app during registration—there is no recovery mechanism.

---

## Audit Log Events Reference

The following events appear in the admin audit log:

| Event | Trigger |
|-------|---------|
| `SUCCESSFUL_REGISTRATION` | New user completes signup |
| `SUCCESSFUL_PASSWORD_AUTH_PENDING_MFA` | Correct password, awaiting TOTP |
| `SUCCESSFUL_MFA_LOGIN` | Full login with MFA |
| `FAILED_LOGIN_ATTEMPT` | Wrong password or TOTP |
| `RATE_LIMIT_TRIGGERED` | Too many failed attempts |
| `SUCCESSFUL_PASSWORD_CHANGE` | Password changed via MFA |
| `COMPANY_CREATED` / `COMPANY_UPDATED` | Company management |
| `JOB_POSTED` / `JOB_UPDATED` / `JOB_DELETED` | Job management |
| `APPLICATION_SUBMITTED` | Job application |
| `APPLICATION_STATUS_CHANGED` | Recruiter updates status |
| `CONVERSATION_CREATED` | New messaging conversation |
| `MESSAGE_SENT` | Message sent in conversation |
