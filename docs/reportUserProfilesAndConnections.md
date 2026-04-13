# Implementation Report: User Profiles and Connections

## Overview

This report documents the full implementation of **Section A: User Profiles and Connections** from the CSE 345/545 course project requirements.

---

## 1. Field-Level Privacy Controls

### Schema Changes (`core/db.py`)

Two new columns added to the `users` table:

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `privacy_profile` | TEXT | `'public'` | Controls who can see bio, headline, location. Values: `public`, `connections`, `private` |
| `show_profile_views` | BOOLEAN | `1` | Whether this user appears in other users' "who viewed me" lists |

A migration block was added so existing databases get the columns via `ALTER TABLE` (silently skipped if already present).

### API Endpoints (`routes/users.py`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/users/me/privacy` | Retrieve current privacy settings |
| `PUT` | `/api/v1/users/me/privacy` | Update `privacy_profile` and/or `show_profile_views` |

**Privacy enforcement** is implemented in `GET /api/v1/users/profile/<email>`:
- If `privacy_profile = 'public'` → full profile visible to everyone
- If `privacy_profile = 'connections'` → bio, headline, location only visible to accepted connections
- If `privacy_profile = 'private'` → only name, email, and role are exposed
- Self-viewing always shows full profile

### Frontend (`profile.html`)

- The privacy dropdown (previously a dead widget) now has `value` attributes (`public`, `connections`, `private`) and an `onchange` handler that calls `PUT /api/v1/users/me/privacy`.
- Save feedback: briefly shows "✓ Saved" in green or error state in red.
- The current privacy value is loaded from the API on page load and pre-selected.
- The "Allow viewers to see I viewed them" checkbox is wired to `show_profile_views` via the same privacy API.

---

## 2. Professional Connections Workflow

### Schema (`core/db.py`)

New table `connections`:

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | INTEGER | PRIMARY KEY |
| `requester_email` | TEXT | FK → users.email |
| `recipient_email` | TEXT | FK → users.email |
| `status` | TEXT | DEFAULT 'pending' (values: pending, accepted, rejected) |
| `created_at` | TIMESTAMP | |
| `updated_at` | TIMESTAMP | |

`UNIQUE(requester_email, recipient_email)` prevents duplicate connection rows.

### API Endpoints (`routes/connections.py`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/connections` | List accepted connections, pending received, pending sent |
| `POST` | `/api/v1/connections/request` | Send connection request (body: `{"email": "..."}`) |
| `PUT` | `/api/v1/connections/<id>/accept` | Accept a pending invitation (recipient only) |
| `PUT` | `/api/v1/connections/<id>/reject` | Reject a pending invitation (recipient only) |
| `DELETE` | `/api/v1/connections/<id>` | Remove/cancel a connection (either party) |
| `GET` | `/api/v1/connections/graph` | Get 1st/2nd degree connections for graph visualization |
| `GET` | `/api/v1/connections/suggestions` | Get suggested users (not already connected) |

**Security features**:
- Only the recipient can accept/reject
- Either party can remove a connection
- Cannot send duplicate requests (409)
- Cannot connect to yourself (400)
- Re-requesting after rejection is allowed (resets status to pending)
- All actions logged to audit trail

### Frontend (`network.html`)

Complete rewrite from static mockup to fully dynamic page:

- **Sidebar**: Real-time stats (connections count, pending sent, pending received)
- **Invitations section**: Lists pending received requests with Accept/Ignore buttons → calls `/accept` and `/reject` APIs
- **My Connections section**: Lists accepted connections with name, headline, and Remove button
- **Suggestions section**: Shows non-connected users with Connect button → calls `/request` API
- After any action, all sections reload automatically

---

## 3. Limited Connection Graph

### API (`routes/connections.py`)

`GET /api/v1/connections/graph` returns:
- **nodes**: Array of `{email, name, headline, degree}` where degree is 0 (self), 1 (direct), or 2 (connection-of-connection)
- **edges**: Array of `{from, to}` representing connections
- 2nd degree connections are limited to 20 to prevent overwhelming the graph

### Frontend (`network.html`)

- **SVG-based graph visualization** with radial layout:
  - Degree 0 (you): center, purple glow, largest node
  - Degree 1 (direct connections): inner ring, green border
  - Degree 2 (friends-of-friends): outer ring, gray border, slightly transparent
- Edges drawn as SVG lines between connected nodes
- Hover effect scales nodes up
- Legend showing degree color meanings
- Empty state displayed when no connections exist

---

## 4. Profile Views Tracking

### Schema (`core/db.py`)

New table `profile_views`:

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | INTEGER | PRIMARY KEY |
| `viewer_email` | TEXT | FK → users.email |
| `viewed_email` | TEXT | FK → users.email |
| `timestamp` | TIMESTAMP | |

### API Endpoints (`routes/users.py`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/users/me/views` | Returns `views_this_week` count and `recent_viewers` list |
| `GET` | `/api/v1/users/profile/<email>` | Viewing another user's profile automatically records a view |

**Privacy integration**:
- Self-views are NOT tracked
- `recent_viewers` only includes users where `show_profile_views = 1`
- Views are counted for the last 7 days
- Recent viewers are grouped by email and sorted by most recent

### Frontend (`profile.html`)

- **Analytics section**: Replaced hardcoded "142 profile views" with live data from `GET /api/v1/users/me/views`
- Shows "X profile view(s) this week" with real count
- Lists recent viewers by name (only those who opted in)
- "Allow viewers to see I viewed them" toggle wired to `show_profile_views` setting

---

## Files Changed

| File | Change |
|------|--------|
| `backend/api/core/db.py` | Added `connections` table, `profile_views` table, `privacy_profile` + `show_profile_views` columns to users, ALTER TABLE migration |
| `backend/api/routes/connections.py` | **NEW** — Full connections blueprint (7 endpoints) |
| `backend/api/routes/users.py` | Added privacy GET/PUT, profile views, other-user profile view with privacy enforcement |
| `backend/api/app.py` | Registered connections blueprint at `/api/v1/connections` |
| `frontend/public/network.html` | Complete rewrite from static to dynamic (invitations, connections, graph, suggestions) |
| `frontend/public/profile.html` | Wired privacy dropdown, profile views analytics, show_profile_views toggle |
