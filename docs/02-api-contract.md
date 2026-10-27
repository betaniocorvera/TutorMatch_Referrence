# TutorMatch A.I. — Mock API Contract

**Phase:** 1 — Foundations  
**Status:** Draft v0.1  
**Base URL:** `/api`  
**Last updated:** 2026-10-27

## 1. Purpose

This contract lets the UI be built against realistic data before the backend exists. The mock layer and the future backend must return the same shapes. If a screen needs data that is not in this document, update this contract first.

## 2. Conventions

- JSON request and response bodies, except photo upload which uses `multipart/form-data`.
- Authentication uses `Authorization: Bearer <token>` in production. The mock layer accepts `Bearer mock-student-001` and `Bearer mock-tutor-001`.
- IDs are opaque strings with prefixes: `usr_`, `prof_`, `sub_`, `req_`, `conv_`, `msg_`, `ses_`, `rev_`, `rep_`, `notif_`.
- Timestamps are ISO 8601 UTC strings: `2026-10-27T08:30:00Z`.
- Availability is stored in the `Asia/Manila` timezone and returned as `day`, `start`, `end` with `HH:mm` values.
- Money is an integer number of **centavos**: `₱350.00` is `35000`. Never use floating-point money.
- Distance is an integer number of **meters**. The UI formats it as kilometres.
- Pagination uses `page` (1-based), `limit` (default 10, maximum 50), and `total`.
- Errors use one shape:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Please check the highlighted fields.",
    "fields": {
      "email": "Enter a valid email address."
    }
  }
}
```

## 3. Enums

| Enum | Values |
|---|---|
| Role | `student`, `tutor` |
| Format | `online`, `in_person`, `both` |
| Level | `elementary`, `high_school`, `senior_high`, `college`, `adult` |
| Profile status | `active`, `away`, `accepting`, `not_accepting` |
| Request status | `pending`, `accepted`, `declined`, `cancelled`, `expired` |
| Conversation status | `locked`, `active`, `blocked`, `archived` |
| Message type | `text`, `system`, `session_proposal`, `voice`, `call_event` |
| Session status | `proposed`, `accepted`, `declined`, `rescheduled`, `completed`, `cancelled` |
| Match band | `excellent`, `good`, `fair`, `low` |
| Report reason | `harassment`, `spam`, `impersonation`, `inappropriate`, `no_show`, `other` |

## 4. Authentication

### POST `/api/auth/register`

Creates an account with a fixed role. Profile setup happens in onboarding.

Request:

```json
{
  "role": "student",
  "name": "Ana Mae Cabahug",
  "email": "ana@example.test",
  "password": "correct-horse-battery"
}
```

Response `201`:

```json
{
  "user": {
    "id": "usr_student_001",
    "role": "student",
    "name": "Ana Mae Cabahug",
    "email": "ana@example.test",
    "emailVerified": false
  },
  "token": "mock-token",
  "onboardingRequired": true
}
```

Rules:
- `role` cannot be changed after registration.
- Email must be unique.
- Password minimum: 8 characters, at least one letter and one number.
- The future backend must hash passwords with bcrypt or argon2. Never store plaintext.

### POST `/api/auth/login`

Request:

```json
{
  "email": "ana@example.test",
  "password": "correct-horse-battery",
  "remember": true
}
```

Response `200`:

```json
{
  "user": {
    "id": "usr_student_001",
    "role": "student",
    "name": "Ana Mae Cabahug",
    "email": "ana@example.test"
  },
  "token": "mock-token",
  "onboardingRequired": false
}
```

### POST `/api/auth/logout`

Response `204` with no body. Invalidate the session or token.

### GET `/api/auth/me`

Response `200`:

```json
{
  "user": {
    "id": "usr_student_001",
    "role": "student",
    "name": "Ana Mae Cabahug",
    "email": "ana@example.test"
  },
  "profile": {
    "id": "prof_student_001",
    "completeness": 78,
    "status": "active"
  }
}
```

### POST `/api/auth/forgot-password` (V1.5)

Request:

```json
{ "email": "ana@example.test" }
```

Response is always `202` with a generic message so the endpoint does not reveal whether an account exists.

## 5. Reference data

### GET `/api/subjects?q=calc`

Response `200`:

```json
{
  "subjects": [
    { "id": "sub_calculus", "name": "Calculus", "category": "Mathematics" },
    { "id": "sub_algebra", "name": "Algebra", "category": "Mathematics" }
  ]
}
```

### GET `/api/levels`

Response `200`:

```json
{
  "levels": [
    { "id": "elementary", "label": "Elementary" },
    { "id": "high_school", "label": "High School" },
    { "id": "senior_high", "label": "Senior High" },
    { "id": "college", "label": "College" },
    { "id": "adult", "label": "Adult learner" }
  ]
}
```

## 6. Profiles

### GET `/api/me/profile`

Returns the private, editable profile.

```json
{
  "profile": {
    "id": "prof_student_001",
    "userId": "usr_student_001",
    "role": "student",
    "name": "Ana Mae Cabahug",
    "photoUrl": null,
    "bio": "Grade 11 STEM student preparing for college entrance exams.",
    "birthdate": "2009-04-12",
    "headline": "Grade 11 STEM student",
    "status": "active",
    "format": "both",
    "area": {
      "barangay": "Del Pilar",
      "city": "Cabadbaran City"
    },
    "subjects": [
      { "id": "sub_calculus", "name": "Calculus", "level": "senior_high" },
      { "id": "sub_physics", "name": "Physics", "level": "senior_high" }
    ],
    "styleTags": ["visual", "step_by_step"],
    "goalTags": ["exam_prep", "conceptual"],
    "budgetMinCentavos": 30000,
    "budgetMaxCentavos": 40000,
    "availability": [
      { "day": "tue", "start": "18:00", "end": "20:00" },
      { "day": "thu", "start": "18:00", "end": "20:00" },
      { "day": "sat", "start": "09:00", "end": "11:00" }
    ],
    "completeness": 78,
    "verified": false,
    "createdAt": "2026-10-01T02:10:00Z",
    "updatedAt": "2026-10-20T09:15:00Z"
  }
}
```

### PATCH `/api/me/profile`

Accepts any subset of profile fields. Returns the updated private profile.

```json
{
  "headline": "Grade 11 STEM student",
  "bio": "Preparing for college entrance exams.",
  "format": "both",
  "area": { "barangay": "Del Pilar", "city": "Cabadbaran City" },
  "subjects": [
    { "id": "sub_calculus", "level": "senior_high" }
  ],
  "budgetMinCentavos": 30000,
  "budgetMaxCentavos": 40000,
  "availability": [
    { "day": "tue", "start": "18:00", "end": "20:00" }
  ]
}
```

### POST `/api/me/photo`

`multipart/form-data` with a `photo` field. Response `201`:

```json
{ "photoUrl": "https://cdn.example.test/profiles/usr_student_001.webp" }
```

### GET `/api/me/completeness`

Response `200`:

```json
{
  "percent": 78,
  "requiredComplete": true,
  "missing": [
    { "field": "photoUrl", "label": "Add a profile photo", "weight": 5 },
    { "field": "bio", "label": "Write a short bio", "weight": 5 }
  ]
}
```

### GET `/api/profiles/:id`

Returns the **public** profile. Private fields are omitted.

```json
{
  "profile": {
    "id": "prof_tutor_001",
    "userId": "usr_tutor_001",
    "role": "tutor",
    "name": "Maria Santos",
    "photoUrl": null,
    "headline": "Math & Calculus tutor",
    "bio": "Licensed math teacher with 6 years of tutoring experience.",
    "status": "accepting",
    "format": "both",
    "area": { "barangay": "Del Pilar", "city": "Cabadbaran City" },
    "distanceMeters": 1800,
    "subjects": [
      { "id": "sub_calculus", "name": "Calculus", "level": "college" },
      { "id": "sub_algebra", "name": "Algebra", "level": "senior_high" }
    ],
    "rateCentavos": 35000,
    "styleTags": ["visual", "step_by_step"],
    "goalTags": ["exam_prep", "conceptual"],
    "availability": [
      { "day": "tue", "start": "18:00", "end": "20:00" },
      { "day": "thu", "start": "18:00", "end": "20:00" },
      { "day": "sat", "start": "09:00", "end": "11:00" }
    ],
    "verified": true,
    "responseTimeMins": 15,
    "lastActiveAt": "2026-10-27T07:40:00Z",
    "reviews": {
      "count": 0,
      "average": null
    }
  }
}
```

## 7. Search

Search is explicit. The client must not call either endpoint on page load unless the user has submitted a search. At least one search criterion is required.

### GET `/api/search/tutors`

Student searching for tutors.

| Query parameter | Type | Notes |
|---|---|---|
| `q` | string | Free-text subject or keyword |
| `subjectId` | string | Exact subject filter |
| `level` | enum | Student's level |
| `format` | enum | `online`, `in_person`, `both` |
| `maxRateCentavos` | integer | Student's maximum hourly budget |
| `availability` | string | Comma-separated slots, e.g. `tue:18:00-20:00,thu:18:00-20:00` |
| `maxDistanceMeters` | integer | Only applies to in-person or both |
| `style` | string | Comma-separated style tags |
| `goal` | string | Comma-separated goal tags |
| `sort` | enum | `score`, `distance`, `rate` |
| `page` | integer | Default 1 |
| `limit` | integer | Default 10, max 50 |

Example:

```http
GET /api/search/tutors?subjectId=sub_calculus&level=senior_high&format=both&maxRateCentavos=40000&availability=tue:18:00-20:00,thu:18:00-20:00&maxDistanceMeters=5000&sort=score&page=1&limit=10
```

Response `200`:

```json
{
  "query": {
    "subjectId": "sub_calculus",
    "level": "senior_high",
    "format": "both",
    "maxRateCentavos": 40000,
    "maxDistanceMeters": 5000
  },
  "total": 1,
  "page": 1,
  "limit": 10,
  "results": [
    {
      "profile": {
        "id": "prof_tutor_001",
        "userId": "usr_tutor_001",
        "role": "tutor",
        "name": "Maria Santos",
        "photoUrl": null,
        "headline": "Math & Calculus tutor",
        "subjects": [
          { "id": "sub_calculus", "name": "Calculus", "level": "college" }
        ],
        "rateCentavos": 35000,
        "format": "both",
        "area": { "barangay": "Del Pilar", "city": "Cabadbaran City" },
        "distanceMeters": 1800,
        "verified": true,
        "responseTimeMins": 15,
        "lastActiveAt": "2026-10-27T07:40:00Z"
      },
      "match": {
        "score": 92,
        "band": "excellent",
        "reasons": [
          { "type": "subject", "label": "Teaches Calculus" },
          { "type": "availability", "label": "Free Tue & Thu, 6–8 PM" },
          { "type": "budget", "label": "Within your ₱400 budget" }
        ],
        "availabilityOverlap": [
          { "day": "tue", "start": "18:00", "end": "20:00" },
          { "day": "thu", "start": "18:00", "end": "20:00" }
        ],
        "warnings": [],
        "breakdown": {
          "subject": 0.35,
          "availability": 0.2,
          "budget": 0.15,
          "distance": 0.15,
          "styleGoal": 0.15
        }
      }
    }
  ],
  "relaxedFilters": [],
  "suggestions": [
    "Try online format to see more tutors",
    "Widen your area to 10 km"
  ]
}
```

### GET `/api/search/students`

Tutor searching for students. Symmetric response shape.

| Query parameter | Type | Notes |
|---|---|---|
| `q` | string | Free-text subject or keyword |
| `subjectId` | string | Exact subject filter |
| `level` | enum | Student level |
| `format` | enum | `online`, `in_person`, `both` |
| `minBudgetCentavos` | integer | Tutor's minimum acceptable budget |
| `availability` | string | Comma-separated slots |
| `maxDistanceMeters` | integer | Only applies to in-person or both |
| `style` | string | Comma-separated style tags |
| `goal` | string | Comma-separated goal tags |
| `sort` | enum | `score`, `distance`, `budget` |
| `page` | integer | Default 1 |
| `limit` | integer | Default 10, max 50 |

### Match object

| Field | Type | Notes |
|---|---|---|
| `score` | integer 0–100 | Pair score, computed from both directions where possible |
| `band` | enum | `excellent`, `good`, `fair`, `low` |
| `reasons` | array | Top 3 positive contributions, derived from actual feature contributions |
| `availabilityOverlap` | array | Slots where both people are free |
| `warnings` | array | Soft conflicts, e.g. rate slightly above budget |
| `breakdown` | object | Optional debug/explanation payload; not shown as raw numbers in V1 |

Reason types: `subject`, `level`, `availability`, `budget`, `distance`, `style`, `goal`, `verification`, `response`.

Rules:
- Hard filters are applied before ranking: role, format, budget (when marked firm), maximum distance, minimum availability overlap.
- Missing profile data is not treated as zero. Use a missing-value mask and a modest penalty.
- A result below the `fair` band may be returned only if the search would otherwise be empty, and must be labelled.
- If filters were relaxed, return them in `relaxedFilters` and show a visible notice in the UI.

## 8. Requests

### POST `/api/requests`

Request:

```json
{
  "toUserId": "usr_tutor_001",
  "subjectId": "sub_calculus",
  "message": "Hi! I need help with Calculus for my senior high exams. Are you free Tuesday evenings?",
  "preferredSlots": [
    { "day": "tue", "start": "18:00", "end": "20:00" }
  ],
  "format": "both"
}
```

Response `201`:

```json
{
  "request": {
    "id": "req_001",
    "fromUserId": "usr_student_001",
    "toUserId": "usr_tutor_001",
    "subjectId": "sub_calculus",
    "message": "Hi! I need help with Calculus for my senior high exams. Are you free Tuesday evenings?",
    "preferredSlots": [
      { "day": "tue", "start": "18:00", "end": "20:00" }
    ],
    "format": "both",
    "status": "pending",
    "createdAt": "2026-10-27T08:00:00Z",
    "expiresAt": "2026-11-03T08:00:00Z"
  }
}
```

Rules:
- Cannot request yourself.
- Must be the opposite role.
- Both profiles must meet the minimum completeness.
- Only one pending request per pair.
- Request limit: 5 per day per user in V1.
- Pending requests expire after 7 days.

### GET `/api/requests?box=incoming&status=pending&page=1&limit=10`

`box` is `incoming` or `outgoing`.

Response `200`:

```json
{
  "total": 1,
  "page": 1,
  "limit": 10,
  "requests": [
    {
      "id": "req_001",
      "direction": "incoming",
      "from": {
        "id": "usr_student_001",
        "name": "Ana Mae Cabahug",
        "photoUrl": null,
        "role": "student"
      },
      "to": {
        "id": "usr_tutor_001",
        "name": "Maria Santos",
        "photoUrl": null,
        "role": "tutor"
      },
      "subject": { "id": "sub_calculus", "name": "Calculus" },
      "message": "Hi! I need help with Calculus for my senior high exams.",
      "preferredSlots": [
        { "day": "tue", "start": "18:00", "end": "20:00" }
      ],
      "format": "both",
      "status": "pending",
      "createdAt": "2026-10-27T08:00:00Z",
      "expiresAt": "2026-11-03T08:00:00Z"
    }
  ]
}
```

### PATCH `/api/requests/:id`

Accept:

```json
{ "action": "accept" }
```

Response `200`:

```json
{
  "request": { "id": "req_001", "status": "accepted" },
  "conversationId": "conv_001"
}
```

Decline or cancel:

```json
{ "action": "decline" }
```

```json
{ "action": "cancel" }
```

Only the recipient can accept or decline. Only the sender can cancel. Declining does not require a reason in V1.

## 9. Conversations and messages

### GET `/api/conversations?tab=all&page=1&limit=20`

Response `200`:

```json
{
  "total": 1,
  "conversations": [
    {
      "id": "conv_001",
      "status": "active",
      "otherUser": {
        "id": "usr_tutor_004",
        "name": "Kevin Lumactod",
        "photoUrl": null,
        "role": "tutor",
        "verified": false
      },
      "subject": { "id": "sub_programming", "name": "Programming" },
      "lastMessage": {
        "id": "msg_003",
        "type": "text",
        "preview": "Sure. I'll send a session proposal.",
        "senderId": "usr_tutor_004",
        "createdAt": "2026-10-27T08:20:00Z"
      },
      "unreadCount": 1,
      "lastMessageAt": "2026-10-27T08:20:00Z"
    }
  ]
}
```

### GET `/api/conversations/:id`

Returns conversation metadata, participants, request status, and the latest session proposal.

```json
{
  "conversation": {
    "id": "conv_001",
    "status": "active",
    "request": {
      "id": "req_002",
      "status": "accepted",
      "subject": { "id": "sub_programming", "name": "Programming" }
    },
    "participants": [
      { "id": "usr_student_002", "name": "Mark Joseph Orquia", "role": "student" },
      { "id": "usr_tutor_004", "name": "Kevin Lumactod", "role": "tutor", "verified": false }
    ],
    "latestSession": {
      "id": "ses_001",
      "status": "proposed",
      "startsAt": "2026-10-29T11:00:00Z",
      "durationMins": 60,
      "format": "online"
    }
  }
}
```

### GET `/api/conversations/:id/messages?before=msg_003&limit=30`

Response `200`:

```json
{
  "messages": [
    {
      "id": "msg_001",
      "conversationId": "conv_001",
      "senderId": null,
      "type": "system",
      "body": "Request accepted. You can now chat.",
      "createdAt": "2026-10-27T08:10:00Z",
      "readAt": null
    },
    {
      "id": "msg_002",
      "conversationId": "conv_001",
      "senderId": "usr_tutor_004",
      "type": "text",
      "body": "Hi Mark, happy to help with Programming. What are you working on?",
      "createdAt": "2026-10-27T08:15:00Z",
      "readAt": "2026-10-27T08:16:00Z"
    }
  ],
  "hasMore": false
}
```

### POST `/api/conversations/:id/messages`

Request:

```json
{
  "type": "text",
  "body": "Hi! We have a Java assignment on arrays. Can we meet Wednesday 7 PM?"
}
```

Response `201`:

```json
{
  "message": {
    "id": "msg_004",
    "conversationId": "conv_001",
    "senderId": "usr_student_002",
    "type": "text",
    "body": "Hi! We have a Java assignment on arrays. Can we meet Wednesday 7 PM?",
    "createdAt": "2026-10-27T08:25:00Z",
    "readAt": null
  }
}
```

Rules:
- Chat is locked until a request between the two users is accepted.
- Locked conversations return `403` with `CHAT_LOCKED`.
- Blocked users cannot send messages.
- V1 message types: `text`, `system`, `session_proposal`. Voice and call events are reserved for later.
- Message length limit: 2,000 characters.
- Rate limit: 30 messages per minute per user.

### PATCH `/api/conversations/:id/read`

Request:

```json
{ "lastMessageId": "msg_004" }
```

Response `204`.

### POST `/api/conversations/:id/report`

Request:

```json
{
  "reason": "harassment",
  "details": "Optional details."
}
```

Response `201`:

```json
{ "reportId": "rep_001", "status": "open" }
```

### POST `/api/conversations/:id/block`

Response `204`. The conversation becomes read-only for both users in the UI.

## 10. Sessions

### POST `/api/sessions`

Request:

```json
{
  "conversationId": "conv_001",
  "startsAt": "2026-10-29T11:00:00Z",
  "durationMins": 60,
  "format": "online",
  "location": "Google Meet link to be shared in chat",
  "note": "Arrays and loops practice."
}
```

Response `201`:

```json
{
  "session": {
    "id": "ses_001",
    "conversationId": "conv_001",
    "proposedBy": "usr_tutor_004",
    "startsAt": "2026-10-29T11:00:00Z",
    "durationMins": 60,
    "format": "online",
    "location": "Google Meet link to be shared in chat",
    "note": "Arrays and loops practice.",
    "status": "proposed",
    "createdAt": "2026-10-27T08:30:00Z"
  }
}
```

Rules:
- `startsAt` must be in the future.
- Duration: 30, 60, 90, or 120 minutes.
- Either participant can propose.
- Only the other participant can accept or decline.
- A system message is created when a session is proposed, accepted, declined, or completed.

### GET `/api/sessions?from=2026-10-27&to=2026-11-03`

Response `200`:

```json
{
  "sessions": [
    {
      "id": "ses_001",
      "conversationId": "conv_001",
      "status": "proposed",
      "startsAt": "2026-10-29T11:00:00Z",
      "durationMins": 60,
      "format": "online",
      "otherUser": { "id": "usr_tutor_004", "name": "Kevin Lumactod" }
    }
  ]
}
```

### PATCH `/api/sessions/:id`

```json
{ "action": "accept" }
```

Allowed actions: `accept`, `decline`, `reschedule`, `cancel`, `complete`.

For `reschedule`, include `startsAt` and optionally `durationMins`.

## 11. Saved profiles (V1.5)

### GET `/api/saved`

```json
{
  "saved": [
    {
      "profileId": "prof_tutor_001",
      "name": "Maria Santos",
      "photoUrl": null,
      "headline": "Math & Calculus tutor",
      "savedAt": "2026-10-27T08:40:00Z"
    }
  ]
}
```

### POST `/api/saved/:profileId`

Response `201`.

### DELETE `/api/saved/:profileId`

Response `204`.

## 12. Notifications

### GET `/api/notifications?unread=true&page=1&limit=20`

Response `200`:

```json
{
  "total": 1,
  "unread": 1,
  "notifications": [
    {
      "id": "notif_001",
      "type": "request_accepted",
      "payload": {
        "requestId": "req_002",
        "conversationId": "conv_001",
        "actorName": "Kevin Lumactod"
      },
      "readAt": null,
      "createdAt": "2026-10-27T08:10:00Z"
    }
  ]
}
```

### PATCH `/api/notifications/:id/read`

Response `204`.

### PATCH `/api/notifications/read-all`

Response `204`.

V1 can derive notifications from requests and messages without a separate push service.

## 13. Safety

### POST `/api/reports`

```json
{
  "reportedUserId": "usr_tutor_004",
  "reason": "no_show",
  "details": "Did not attend the agreed session.",
  "conversationId": "conv_001"
}
```

Response `201`:

```json
{ "reportId": "rep_001", "status": "open" }
```

### POST `/api/blocks/:userId`

Response `204`.

### DELETE `/api/blocks/:userId`

Response `204`.

### GET `/api/blocks`

Returns the current user's blocked list. Never expose this list to other users.

## 14. Analytics events

### POST `/api/events`

Used for capstone evaluation and product analytics.

```json
{
  "name": "search_submitted",
  "payload": {
    "role": "student",
    "subjectId": "sub_calculus",
    "filters": {
      "format": "both",
      "maxRateCentavos": 40000
    },
    "resultCount": 12
  }
}
```

Suggested events:
- `search_submitted`
- `result_clicked`
- `profile_viewed`
- `request_sent`
- `request_accepted`
- `request_declined`
- `message_sent`
- `session_proposed`
- `session_completed`
- `report_submitted`

Do not include passwords, emails, or message bodies in analytics payloads.

## 15. Error codes

| HTTP | Code | Meaning |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Missing or invalid fields |
| 401 | `UNAUTHORIZED` | Missing or expired session |
| 403 | `FORBIDDEN` | Wrong role or no permission |
| 403 | `CHAT_LOCKED` | Request not accepted yet |
| 403 | `PROFILE_INCOMPLETE` | Profile below the search/request minimum |
| 403 | `BLOCKED` | One user has blocked the other |
| 404 | `NOT_FOUND` | Resource does not exist |
| 409 | `CONFLICT` | Duplicate request or account |
| 409 | `REQUEST_EXISTS` | Pending request already exists |
| 422 | `SELF_REQUEST` | User tried to request themselves |
| 429 | `RATE_LIMITED` | Too many requests or messages |
| 500 | `INTERNAL` | Unexpected server error |

## 16. Mock behavior

The mock layer should behave like a real API:

- 300–700 ms artificial latency.
- Deterministic fixture data from `mock/seed.json`.
- Role enforcement for search, requests, and chat.
- Simulated errors for duplicate requests, locked chat, incomplete profiles, and rate limits.
- No real personal data. All names and emails are fictional.
- Mock auth accepts `Bearer mock-student-001` and `Bearer mock-tutor-001`; do not ship this to production.
- Search must not run on page load. The UI only calls search after the user submits.

## 17. Privacy contract

Public profile responses must never include:

- Email address
- Birthdate
- Exact coordinates
- Password hash
- Verification documents
- Reports or block list

Location responses include barangay, city, and rounded distance only. Chat messages are returned only to the two participants. Admin endpoints are authenticated and role-restricted.

## 18. Mapping to the backend

| Contract area | Future tables |
|---|---|
| Auth | `users`, `sessions` |
| Profiles | `profiles`, `subjects`, `profile_subjects`, `availability_slots` |
| Search | `profiles`, `profile_subjects`, `availability_slots` + KNN service |
| Requests | `match_requests`, `conversations` |
| Messages | `conversations`, `messages` |
| Sessions | `session_proposals` |
| Saved | `saved_profiles` |
| Notifications | `notifications` |
| Safety | `reports`, `blocks` |
| Analytics | `analytics_events` |
