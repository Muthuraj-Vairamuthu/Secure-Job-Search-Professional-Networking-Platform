# April Milestone Report Guide

This document is a simple report template and evidence checklist for the April Milestone final evaluation.

It is written in clear language, while still using technical terms where needed.

---

# Secure Job Search & Professional Networking Platform

## Final Evaluation Report

### Team
- FCS Group 19

### Milestone Covered
- April Milestone (Final Evaluation)
- Bonus Features

---

## 1. Introduction

We built a secure job search and professional networking platform that supports:

- user registration and login
- multi-factor authentication
- profile management
- company pages and job postings
- job applications and status tracking
- secure messaging
- admin monitoring and moderation

The main focus of the April milestone was security. We implemented Public Key Infrastructure (PKI), OTP input through a virtual keyboard, tamper-evident audit logging, and defenses against common web attacks. We also completed both bonus features: blockchain-style logging and resume parsing with intelligent matching.

---

## 2. PKI Integration

We used PKI in two security-critical functions:

### 2.1 Resume Digital Signature

When a user uploads a resume:

- the plaintext resume is hashed using SHA-256
- the hash is signed using the user’s RSA-2048 private key
- the signature is stored with the resume

When the resume is downloaded:

- the signature is automatically verified
- the system returns the verification result in the response header `X-PKI-Signature-Status`

This gives resume integrity verification and helps detect tampering.

### 2.2 Message Signing

When a message is sent:

- the encrypted message content is signed with the sender’s RSA private key
- the signature is stored in the database

Later, the message can be verified using the sender’s public key.

This provides non-repudiation and integrity for secure messaging.

### Screenshot You Should Add

1. Upload a resume successfully and show the response or UI state.
2. Show the resume verification endpoint output:
   - `GET /api/v1/users/resumes/<id>/verify`
3. Show a message verification response:
   - `GET /api/v1/messages/messages/<id>/verify`
4. In browser DevTools, show the response header:
   - `X-PKI-Signature-Status: valid`

---

## 3. OTP with Virtual Keyboard

We implemented a randomized virtual keyboard for high-risk actions.

The digit layout changes every time the keyboard opens. This helps reduce the risk of shoulder surfing and simple keylogging attacks.

### High-Risk Actions Protected

1. Login OTP entry
2. Resume download
3. Password change

### How It Works

- physical keyboard input is blocked for the OTP overlay
- digits are entered using the on-screen randomized keypad
- entered digits are masked as bullets
- OTP is validated before the action is allowed

### Screenshot You Should Add

1. Login OTP screen with virtual keyboard open
2. Resume download verification popup
3. Password change verification popup

### Short Video You Should Record

Record a short video showing:

1. open login OTP virtual keyboard
2. close it
3. reopen it
4. show that the digit order changes
5. enter OTP and log in successfully

That one video is enough to demonstrate randomized layout + high-risk OTP protection.

---

## 4. Tamper-Evident Secure Audit Logs

We implemented secure audit logging in two layers.

### 4.1 Hash-Chained Logs

For each critical log entry, the system stores:

- `prev_hash`
- `log_hash`

The new `log_hash` is computed using:

`SHA-256(prev_hash | email | event | timestamp | ip_address)`

This means if any earlier log entry is changed, the chain breaks.

### 4.2 Blockchain-Style Log Blocks

As a bonus enhancement, we grouped log entries into blocks.

Each block stores:

- `start_log_id`
- `end_log_id`
- `entry_count`
- `merkle_root`
- `prev_block_hash`
- `nonce`
- `block_hash`

We used a lightweight proof-style block generation with a nonce and hash prefix requirement. This gives a private blockchain-like integrity layer on top of the normal audit chain.

### Verification

The admin verification process checks:

- individual log chain integrity
- Merkle root correctness
- block hash correctness
- previous block linkage

### Screenshot You Should Add

1. Admin dashboard audit tab
2. Blockchain verification success result in admin page
3. API response from:
   - `GET /api/v1/admin/audit/verify`

### Optional Extra Screenshot

If you want stronger evidence:

4. Show the `audit_logs` table with `prev_hash` and `log_hash`
5. Show the `log_blocks` table with `merkle_root`, `prev_block_hash`, `block_hash`

---

## 5. Defenses Against Common Web Attacks

We implemented multiple defenses:

### 5.1 SQL Injection Defense

- parameterized SQL queries are used
- raw string concatenation for user input is avoided

### 5.2 XSS Defense

- user content is inserted with safe text rendering
- HTML is escaped before display in dynamic UI

### 5.3 CSRF Protection

- CSRF token is generated and stored in the session
- frontend automatically injects `X-CSRF-Token`
- backend checks the token on state-changing requests

### 5.4 Session Security

- session cookie uses `HttpOnly`, `Secure`, and `SameSite=Strict`
- sessions are bound to IP and User-Agent
- session rotation is supported

### 5.5 Password Security

- passwords are hashed with Argon2id
- plaintext passwords are never stored

### 5.6 Sensitive File Protection

- resumes are encrypted at rest
- strict role-based access control is enforced

### Screenshot You Should Add

1. Cookie view showing:
   - `session_id`
   - `csrf_token`
   - secure flags
2. DevTools request showing `X-CSRF-Token`
3. Database screenshot showing Argon2 password hash
4. Encrypted resume file on disk (`.enc`) instead of readable PDF

### Optional Terminal Evidence

You can also include terminal screenshots for:

- failed CSRF request returning 403
- invalid session on IP/User-Agent mismatch
- SQL injection attempt returning safe failure

---

## 6. Bonus Feature 1: Blockchain-Based Logging

We extended the tamper-evident audit system into a lightweight private blockchain model.

Main additions:

- log entries grouped into blocks
- Merkle root computed for each block
- each block linked to the previous block
- block verification available through admin tools

This improves integrity verification beyond simple row-by-row hash chaining.

### Screenshot You Should Add

1. Admin page showing blockchain verification
2. API response showing:
   - `chain_valid`
   - `blockchain_valid`
   - `total_blocks`

---

## 7. Bonus Feature 2: Resume Parsing and Intelligent Matching

We implemented resume parsing and job matching to help recruiters review applicants faster.

### How It Works

- when a resume is uploaded, the system extracts text from PDF/DOCX
- it detects likely technical skills using pattern matching
- when a recruiter views applicants for a job, the system compares:
  - job title
  - job description
  - required skills
  against the parsed resume content
- it generates:
  - match score
  - matched skills
  - missing skills

### Recruiter Benefit

Recruiters can quickly shortlist candidates based on resume relevance.

### Screenshot You Should Add

1. Upload a resume and show extracted skill output if visible
2. Recruiter applicant view showing:
   - match percentage
   - matched skills
   - missing skills

---

## 8. Final Conclusion

The April milestone requirements were implemented with a strong focus on practical security and usability.

We completed:

- PKI integration for multiple security-critical operations
- OTP with virtual keyboard for high-risk actions
- tamper-evident audit logging
- common web attack defenses

We also completed both bonus features:

- blockchain-style tamper-evident logging
- resume parsing with intelligent applicant matching

The final platform demonstrates secure design across authentication, document handling, messaging, admin auditing, and recruiter workflows.

---

## 9. Evidence Checklist

Use this checklist while preparing the submission.

### Screenshots

- Login OTP virtual keyboard open
- Resume download OTP verification
- Password change OTP verification
- Resume verify API response
- Message verify API response
- DevTools header with `X-PKI-Signature-Status`
- Admin audit tab
- Admin blockchain verification result
- Applicant match score view in recruiter dashboard
- Cookie flags (`session_id`, `csrf_token`)
- CSRF header in DevTools
- Argon2 password hash in DB
- Encrypted resume file on disk

### Video

Record one short video that shows:

1. login with virtual keyboard
2. digit layout changes after reopening keyboard
3. resume upload
4. recruiter applicant matching view
5. admin blockchain verification

That single video can cover most of the milestone proof in one flow.

---

## 10. Suggested Screenshot Captions

You can use these simple captions in the report:

- Figure 1: OTP entry using randomized virtual keyboard during login
- Figure 2: Resume download protected by OTP verification
- Figure 3: PKI-based resume signature verification response
- Figure 4: PKI-based message signature verification response
- Figure 5: Admin dashboard showing tamper-evident audit logs
- Figure 6: Blockchain verification result for audit blocks
- Figure 7: Recruiter dashboard showing intelligent resume-job match score
- Figure 8: Secure cookies and CSRF token handling in browser
- Figure 9: Argon2 password hashing in the database
- Figure 10: Encrypted resume stored on disk
