# Secure Job Search & Professional Networking Platform

A security-focused job search and professional networking platform built for the April Milestone evaluation. The system supports user profiles, professional connections, company pages, job postings, application tracking, secure resume handling, end-to-end encrypted messaging, admin moderation, and multiple security controls including PKI, OTP verification, CSRF protection, session binding, tamper-evident logging, and blockchain-style audit verification.

## Features

### Core Platform
- User registration and login with MFA/TOTP
- Profile management with privacy controls
- Professional connection requests, accept/reject, removal, and graph visualization
- Company page creation and management for recruiters
- Job posting, search, filtering, and application workflow
- Application tracking with recruiter status updates
- Secure recruiter-candidate messaging
- Admin dashboard for monitoring and moderation

### Security Features
- PKI integration for:
  - Resume digital signatures and integrity verification
  - Message signing and verification
- OTP virtual keyboard for high-risk actions:
  - Login OTP entry
  - Resume download
  - Password change
- Tamper-evident audit logging with:
  - Hash-chained audit entries
  - Blockchain-style audit blocks with Merkle roots
- CSRF protection with per-session tokens
- Session binding to IP address and User-Agent
- Session rotation support
- Secure cookie flags (`HttpOnly`, `Secure`, `SameSite=Strict`)
- Resume encryption at rest
- Protection against SQL injection, XSS, CSRF, session hijacking, and session fixation

### Bonus Features
- Blockchain-based tamper-evident audit verification
- Resume parsing and intelligent recruiter-side matching

## Tech Stack

- Backend: Python + Flask
- Frontend: HTML, CSS, JavaScript
- Database: SQLite
- Reverse Proxy / TLS: Nginx
- Cryptography:
  - Argon2id for password hashing
  - TOTP for MFA
  - RSA-2048 for PKI signing
  - Encrypted-at-rest document storage

## Project Structure

```text
backend/
  api/
    app.py
    core/
    routes/
    pki.py
    auth_secTOTP.py
    secureResumeUpload.py
    resume_matching.py
  certs/
  data/
  nginx.conf

frontend/
  public/
  js/
  css/

tests/
docs/
```

## Setup

### 1. Clone the repository
```bash
git clone https://github.com/Muthuraj-Vairamuthu/Secure-Job-Search-Professional-Networking-Platform.git
cd Secure-Job-Search-Professional-Networking-Platform
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Run the application
```bash
python3 backend/api/app.py
```

Optional environment variables:

```bash
export ADMIN_SIGNUP_CODE="your-secret-admin-code"
export SIGNUP_CONTEXT_SECRET="another-long-random-secret"
```

`ADMIN_SIGNUP_CODE` is required to create new admin accounts from the signup UI.
`SIGNUP_CONTEXT_SECRET` protects the multi-step signup context from client-side tampering.

The app runs at:

```text
http://localhost:8000
```

## Main Pages

- `/` - landing page
- `/auth.html` - login and signup
- `/dashboard.html` - main dashboard
- `/profile.html` - user profile and resume management
- `/network.html` - professional connections
- `/jobs.html` - job search and applications
- `/messages.html` - secure messaging
- `/company.html` - recruiter company/job management
- `/admin.html` - admin dashboard

## Security Highlights

### PKI
- Resumes are signed on upload
- Messages are signed on send
- Verification APIs are provided for both

### OTP Virtual Keyboard
- Randomized keypad layout
- Masked digit entry
- Used for sensitive actions

### Audit Integrity
- Every critical audit log is hash chained
- Audit logs are grouped into blockchain-style blocks
- Admin verification checks both entry-chain and block-chain integrity

### Resume Security
- Encrypted at rest
- Secure deletion supported
- Recruiter access restricted to authorized application context

## Demo Checklist

Recommended demo flow:
1. Register and verify a user
2. Log in with OTP virtual keyboard
3. Upload and verify a signed resume
4. Create a recruiter company and post a job
5. Apply to a job with a resume
6. Show recruiter applicant matching
7. Send a signed secure message
8. Open the admin dashboard and verify the audit blockchain

## Documentation

See the `docs/` folder for:
- manual testing guides
- audit report
- April milestone report guide

## Notes

- Email verification is implemented using simulated delivery/logging.
- MFA is implemented with TOTP.
- The platform is designed for academic demonstration and security evaluation.

## Authors

FCS Group 19
