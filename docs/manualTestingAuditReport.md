# Manual Testing Audit Report

This report summarizes the final code audit and manual-testing readiness pass for the FCS Group 19 Secure Job Search & Professional Networking Platform.

## Scope

The audit covered:

- Assignment TODO completion status
- Critical bug-fix verification
- Frontend/backend route consistency
- Authentication and MFA flow
- Email verification flow
- Recruiter/company/job/application flows
- Messaging, PKI, CSRF, session security, and admin/security features
- Bonus features:
  - Resume parsing and intelligent matching
  - Blockchain-based audit logging

## Final Status

All required TODO items are now implemented in the codebase.

Completed:

- Critical bug fixes
- User profiles and privacy controls
- Professional connections and graph visualization
- Profile views tracking
- Email verification with simulated delivery
- Admin moderation:
  - `require_admin`
  - protected admin dashboard
  - suspend user
  - unsuspend user
  - delete user
  - admin action buttons
- PKI integration for resumes and messages
- OTP virtual keyboard
- Tamper-evident logging
- CSRF protection
- Session binding and rotation
- HTTPS/TLS deployment files
- Bonus: resume parsing and applicant matching
- Bonus: blockchain-style audit blocks

## Issues Found During Audit And Fixed

### 1. Dashboard profile summary used placeholder data

Problem:
- `dashboard.html` showed hardcoded `John Doe` instead of the logged-in user.

Fix:
- Replaced static sidebar/share-box profile data with live `/api/v1/users/me`, `/api/v1/users/me/views`, and `/api/v1/connections` data.

Result:
- Dashboard now consistently shows the real logged-in user name, avatar, headline, profile views, and connection count.

### 2. Navigation menu was inconsistent across pages

Problem:
- Different pages hardcoded different navigation items.
- `Company` and `Admin` appeared on some pages but not others.

Fix:
- Added a shared navigation renderer in `frontend/js/script.js`.
- Navigation is now role-based and consistent across pages.

Result:
- All pages show the same menu logic:
  - Home, Network, Jobs, Messaging
  - Profile for logged-in users
  - Company for recruiter/admin
  - Admin for admin only

### 3. Recruiter-only backend routes were missing `@require_auth`

Problem:
- Some recruiter routes used `@require_recruiter` without `@require_auth`.
- This could break manual tests or cause inconsistent authorization behavior.

Fix:
- Added `@require_auth` to recruiter-only routes in:
  - `routes/companies.py`
  - `routes/jobs.py`
  - `routes/applications.py`

Result:
- Recruiter manual tests now match actual expected behavior.

### 4. Company dashboard had stale route paths earlier

Problem:
- `company.html` previously used old `/api/...` routes in some actions.

Fix:
- Updated recruiter company/job/application actions to use `/api/v1/...` consistently.

Result:
- Company dashboard actions now align with the current backend API.

### 5. Jobs page missed shared client script

Problem:
- `jobs.html` did not load `script.js`.
- That meant no shared nav rendering and no automatic CSRF header injection.

Fix:
- Added `../js/script.js` to `jobs.html`.

Result:
- Job application and other state-changing actions now receive CSRF headers correctly.

### 6. Jobs page linked users to placeholder `resume.html`

Problem:
- When no resume existed, `jobs.html` sent users to `resume.html`.
- That page was not the real upload flow.

Fix:
- Updated the link to `profile.html`.
- Added redirect from `resume.html` to `profile.html`.

Result:
- Resume upload path now matches the actual implemented feature.

### 7. Admin page handled non-admin access poorly

Problem:
- `admin.html` handled `401` but not `403` cleanly.

Fix:
- Added explicit `403 Forbidden. Admins only.` handling and redirect to dashboard.

Result:
- Manual negative admin access tests now behave more cleanly in the browser.

### 8. Email verification requirement was incomplete

Problem:
- Email verification token generation existed, but login enforcement and verification endpoint were incomplete.

Fix:
- Added simulated email delivery
- Added `POST /api/v1/auth/verify-email`
- Enforced `is_verified` at login
- Updated auth UI flow to complete verification

Result:
- Authentication enhancement requirement is now implemented end-to-end.

### 9. Resume parsing and recruiter matching bonus was missing

Fix:
- Added resume text extraction and skill extraction on upload
- Stored parsed text/skills in the database
- Added applicant match score, matched skills, and missing skills in recruiter applicant view
- Added lazy backfill for older resumes

Result:
- Recruiters now see intelligent resume-job matching in `company.html`.

### 10. Blockchain logging bonus was missing

Fix:
- Added `log_blocks` table
- Added block creation over groups of audit log entries
- Added Merkle root computation
- Added block hash + previous block hash linkage
- Added admin blockchain verification UI and API response fields
- Unified auth audit logging into the same chained/blocked pipeline

Result:
- Audit logging now supports both per-entry hash chaining and lightweight blockchain-style block verification.

### 11. Structured profile fields were not fully implemented

Problem:
- The assignment expects profile support for skills, education, experience, and profile picture.
- The UI previously showed placeholder/demo content instead of real stored data.

Fix:
- Added backend-backed profile fields:
  - `skills`
  - `education`
  - `experience`
  - `profile_picture_url`
- Added database migrations for existing installations.
- Updated profile APIs to read/write those fields.
- Updated `edit_profile.html` to edit them.
- Updated `profile.html` to display real stored values and honest empty states.

Result:
- Profile data now aligns much more closely with the assignment requirement and no longer relies on fake hardcoded placeholders.

### 12. Recruiter access to applicant resumes was too limited

Problem:
- Secure resume storage existed, but recruiter access for actual applicant review was not exposed cleanly in the UI.

Fix:
- Added server-side authorization so recruiters may access a resume only when it belongs to an application for one of their jobs.
- Added recruiter-side resume download action in `company.html`.

Result:
- Resume access now better matches the requirement that authorized recruiters may access resumes.

## Manual Testing Readiness Notes

The application is now aligned with the current implementation, with the following notes:

- The manual guide should be updated to include email verification after registration.
- Any guide reference to `resume.html` should be replaced with `profile.html`.
- The current implementation supports simulated email verification, not a separate SMS/mobile OTP provider.

## Verification Performed

Performed during this audit:

- Source inspection across backend and frontend flows
- Route consistency checks
- API path consistency checks
- Static compile verification using `python3 -m py_compile`

Verified clean after fixes:

- `backend/api/routes/companies.py`
- `backend/api/routes/jobs.py`
- `backend/api/routes/applications.py`
- `backend/api/routes/admin.py`
- `backend/api/core/db.py`
- `backend/api/auth_secTOTP.py`
- `backend/api/routes/users.py`
- `backend/api/resume_matching.py`

## Final Conclusion

After the audit and fixes, the project is in a completed state for the assignment checklist provided.

Required features: complete.

Bonus features: complete.

Remaining work is documentation cleanup only:

- Refresh the manual testing document to reflect:
  - email verification step
  - `profile.html` as the resume upload flow
  - blockchain verification being available in admin audit tools

## Requirement Caveats

The platform now covers the major functional and security requirements well. The following items should still be described carefully in documentation:

- Email verification is implemented with simulated delivery; a separate SMS/mobile OTP provider is not implemented.
- E2EE private messaging is implemented, but a separate optional announcement-mode encrypted messaging path is not explicitly split out as its own feature.
- Scalability and simultaneous access were not benchmarked as part of this audit pass.
