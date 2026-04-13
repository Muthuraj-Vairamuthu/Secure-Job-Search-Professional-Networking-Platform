# Manual Testing Guide: User Profiles and Connections

> **Prerequisites**: Server running (`python3 backend/api/app.py`), at least 2 registered users with TOTP set up. See `manualTesting.md` Section 2 for registration steps.

---

## Table of Contents

1. [Privacy Controls](#1-privacy-controls)
2. [Connection Requests](#2-connection-requests)
3. [Accept / Reject Invitations](#3-accept--reject-invitations)
4. [Remove Connections](#4-remove-connections)
5. [Connection Graph Visualization](#5-connection-graph-visualization)
6. [Connection Suggestions](#6-connection-suggestions)
7. [Profile Views Tracking](#7-profile-views-tracking)
8. [Privacy Enforcement on Profile Viewing](#8-privacy-enforcement-on-profile-viewing)
9. [Negative Tests](#9-negative-tests)

---

## 1. Privacy Controls

*Prerequisite: Logged in as any user.*

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1.1 | Navigate to `profile.html` | Privacy dropdown shows current setting (default: "Public") |
| 1.2 | Change dropdown to **"Connections Only"** | "✓ Saved" appears briefly in green next to the dropdown |
| 1.3 | Refresh the page | Dropdown still shows "Connections Only" (persisted) |
| 1.4 | Change to **"Private"** | Saves successfully |
| 1.5 | Uncheck **"Allow viewers to see I viewed them"** | Setting saved silently |

### API Verification

```bash
# Check privacy settings
curl -s http://localhost:8000/api/v1/users/me/privacy \
  --cookie "session_id=<SESSION>" | python3 -m json.tool

# Expected: {"status": "success", "privacy_profile": "private", "show_profile_views": false}

# Update privacy
curl -s -X PUT http://localhost:8000/api/v1/users/me/privacy \
  -H "Content-Type: application/json" \
  --cookie "session_id=<SESSION>" \
  -d '{"privacy_profile": "public", "show_profile_views": true}' | python3 -m json.tool
```

---

## 2. Connection Requests

*Prerequisite: 2 users registered (User A and User B), logged in as User A.*

| Step | Action | Expected Result |
|------|--------|-----------------|
| 2.1 | Navigate to `network.html` | Page loads with sections: Invitations, My Connections, Network Visualization, Suggestions |
| 2.2 | In **"People you may know"**, find User B and click **Connect** | Button action triggers; page refreshes; User B disappears from suggestions |
| 2.3 | Check sidebar stats | "Pending Sent" shows 1 |
| 2.4 | Check audit log (admin panel) | `CONNECTION_REQUEST_SENT to <userB@email>` logged |

### API Verification

```bash
# Send connection request
curl -s -X POST http://localhost:8000/api/v1/connections/request \
  -H "Content-Type: application/json" \
  --cookie "session_id=<USER_A_SESSION>" \
  -d '{"email": "userB@test.com"}' | python3 -m json.tool

# Expected: {"status": "success", "message": "Connection request sent", "connection_id": 1}
```

---

## 3. Accept / Reject Invitations

*Prerequisite: User A sent a request to User B. Now log in as User B.*

| Step | Action | Expected Result |
|------|--------|-----------------|
| 3.1 | Navigate to `network.html` as User B | **Invitations** section shows User A with Accept/Ignore buttons |
| 3.2 | Sidebar shows "Invitations: 1" | Count matches |
| 3.3 | Click **Accept** | Invitation disappears; User A appears in "My Connections" with green "Connected" badge |
| 3.4 | Sidebar updates to "Connections: 1", "Invitations: 0" | Stats correct |
| 3.5 | Check audit log | `CONNECTION_ACCEPTED from <userA@email>` logged |

### Reject Flow

| Step | Action | Expected Result |
|------|--------|-----------------|
| 3.6 | (Setup: create another request from User C to User B) | |
| 3.7 | Click **Ignore** on User C's invitation | Invitation removed; User C does NOT appear in connections |
| 3.8 | Audit log shows `CONNECTION_REJECTED` | |

---

## 4. Remove Connections

*Prerequisite: User A and User B are connected.*

| Step | Action | Expected Result |
|------|--------|-----------------|
| 4.1 | In `network.html`, find User B in "My Connections" | User B listed with red remove button (👤➖) |
| 4.2 | Click remove button | Confirmation prompt: "Remove this connection?" |
| 4.3 | Confirm | User B removed from connections list; User B appears in suggestions again |
| 4.4 | Sidebar stats update | Connection count decremented |
| 4.5 | Audit log | `CONNECTION_REMOVED with <userB@email>` |

### API Verification

```bash
# Remove connection
curl -s -X DELETE http://localhost:8000/api/v1/connections/<conn_id> \
  --cookie "session_id=<SESSION>" | python3 -m json.tool
```

---

## 5. Connection Graph Visualization

*Prerequisite: User A has at least 2 connections. One of those connections has their own connections.*

| Step | Action | Expected Result |
|------|--------|-----------------|
| 5.1 | Navigate to `network.html` | Graph area renders with nodes and edges |
| 5.2 | Center node = "You" (purple glow, largest) | Self-node at center |
| 5.3 | Inner ring = 1st degree connections (green border) | Direct connections in ring around center |
| 5.4 | Outer ring = 2nd degree connections (gray, slightly transparent) | Friends-of-friends visible |
| 5.5 | SVG lines connect nodes | Edges drawn between connected users |
| 5.6 | Hover over a node | Node scales up slightly |
| 5.7 | Legend at bottom | Shows color meanings: purple=You, green=1st, gray=2nd |

### With No Connections

| Step | Action | Expected Result |
|------|--------|-----------------|
| 5.8 | New user with 0 connections visits `network.html` | Graph shows empty state: "Connect with others to see your network graph" |

### API Verification

```bash
curl -s http://localhost:8000/api/v1/connections/graph \
  --cookie "session_id=<SESSION>" | python3 -m json.tool

# Expected: {"status": "success", "nodes": [...], "edges": [...]}
```

---

## 6. Connection Suggestions

| Step | Action | Expected Result |
|------|--------|-----------------|
| 6.1 | Navigate to `network.html` | "People you may know" section shows users not yet connected |
| 6.2 | Each card shows avatar, name, headline, and Connect button | Data from API, not hardcoded |
| 6.3 | After connecting to all users | Message: "No suggestions available. All users are already connected!" |
| 6.4 | After a connection is removed | That user reappears in suggestions |

---

## 7. Profile Views Tracking

*Prerequisite: User A and User B exist.*

| Step | Action | Expected Result |
|------|--------|-----------------|
| 7.1 | As User B, view User A's profile via `GET /api/v1/users/profile/<userA@email>` | Profile data returned; view recorded |
| 7.2 | As User A, go to `profile.html` | Analytics section shows "1 profile view this week" |
| 7.3 | Have User B view the profile again | Count increments to 2 |
| 7.4 | Recent viewers section shows User B's name | Only if User B has `show_profile_views = true` |
| 7.5 | User B unchecks "Allow viewers to see I viewed them" | User B disappears from recent viewers list (count still includes them) |

### API Verification

```bash
# View someone's profile (triggers view tracking)
curl -s http://localhost:8000/api/v1/users/profile/userA@test.com \
  --cookie "session_id=<USER_B_SESSION>" | python3 -m json.tool

# Check your own views
curl -s http://localhost:8000/api/v1/users/me/views \
  --cookie "session_id=<USER_A_SESSION>" | python3 -m json.tool

# Expected: {"status": "success", "views_this_week": 2, "recent_viewers": [...]}
```

---

## 8. Privacy Enforcement on Profile Viewing

*Prerequisite: User A and User B are registered. User A sets privacy to "connections".*

### Test: Connections Only

| Step | Action | Expected Result |
|------|--------|-----------------|
| 8.1 | User A sets privacy to **"Connections Only"** via `profile.html` | Saved |
| 8.2 | User B (NOT connected) views User A's profile via API | Response has `"full_access": false, "privacy_restricted": true` — no bio, headline, location |
| 8.3 | User B sends connection request, User A accepts | Now connected |
| 8.4 | User B views User A's profile again | Response has `"full_access": true` — bio, headline, location included |

### Test: Private

| Step | Action | Expected Result |
|------|--------|-----------------|
| 8.5 | User A sets privacy to **"Private"** | Saved |
| 8.6 | User B (even if connected) views profile | Only name, email, role returned; `"privacy_restricted": true` |

### Test: Public (default)

| Step | Action | Expected Result |
|------|--------|-----------------|
| 8.7 | User A sets privacy to **"Public"** | Saved |
| 8.8 | Any user views profile | Full profile returned |

```bash
# View as non-connected user
curl -s http://localhost:8000/api/v1/users/profile/userA@test.com \
  --cookie "session_id=<NON_CONNECTED_USER_SESSION>" | python3 -m json.tool

# If privacy=connections and NOT connected:
# {"status":"success","email":"userA@test.com","name":"User A","role":"user","full_access":false,"privacy_restricted":true,"is_connected":false}
```

---

## 9. Negative Tests

| Step | Action | Expected Result |
|------|--------|-----------------|
| 9.1 | Send connection request to yourself | "Cannot connect to yourself" (400) |
| 9.2 | Send duplicate connection request | "Connection request already pending" (409) |
| 9.3 | Send request to already-connected user | "Already connected" (409) |
| 9.4 | Send request to non-existent email | "User not found" (404) |
| 9.5 | User A tries to accept their OWN outgoing request | "Only the recipient can accept" (403) |
| 9.6 | Accept a non-pending (already accepted) connection | "Cannot accept a accepted connection" (400) |
| 9.7 | User C tries to delete User A–B connection | "Permission denied" (403) |
| 9.8 | Set `privacy_profile` to invalid value (e.g., "secret") | "No valid privacy settings provided" (400) |
| 9.9 | View profile of non-existent user | "User not found" (404) |

```bash
# Self-connect
curl -s -X POST http://localhost:8000/api/v1/connections/request \
  -H "Content-Type: application/json" \
  --cookie "session_id=<SESSION>" \
  -d '{"email": "my_own@email.com"}' | python3 -m json.tool

# Expected: {"status": "error", "message": "Cannot connect to yourself"}
```
