# Data Structure — MongoDB

All application data lives in the MongoDB database **`Reservations`** (Atlas), across three
collections. Passwords are **never stored in plaintext** — only a one-way
`werkzeug` hash is kept, so even a full DB dump cannot reveal a user's password.

Connection and secrets are supplied via environment variables (`MONGO_URI`,
`SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`) — see [handover_api.py](handover_api.py).

---

## `users`

One document per person who can sign in.

| Field | Type | Notes |
|---|---|---|
| `_id` | ObjectId | Primary key. |
| `username` | string | Unique, lowercase. Login handle. Immutable after creation. |
| `name` | string | Display name shown throughout the app. |
| `password_hash` | string | `werkzeug` PBKDF2 hash. **No plaintext, ever.** |
| `role` | string | One of `normal`, `supervisor`, `manager`, `admin`. |
| `departments` | string[] | Departments the user belongs to (e.g. `["Housekeeping"]`). |
| `active` | bool | Deactivated users cannot log in. |
| `must_change_password` | bool | `true` forces a password change on next login (new accounts & resets). |
| `created_at` | datetime | Creation timestamp (UTC). |

**Roles / permissions**

| Role | Handovers | Delete | Activity log | User management |
|---|---|---|---|---|
| normal | create, comment, update status, request delete | request only | — | — |
| supervisor | + edit/reassign any task | request only | — | — |
| manager | + edit across departments | request only | own department(s) + self | create/reset/edit staff (normal & supervisor) in own department(s) |
| admin | everything | **delete** & approve requests | all departments | all accounts & roles |

---

## `tasks`

One document per handover.

| Field | Type | Notes |
|---|---|---|
| `_id` | ObjectId | Primary key. |
| `title` | string | Short description. |
| `department` | string[] | One or more departments the handover concerns. |
| `priority` | string | `Normal`, `High`, or `Low`. |
| `status` | string | `Pending`, `In Progress`, or `Completed`. |
| `task_date` | string | Raw date or `"YYYY-MM-DD to YYYY-MM-DD"` range. |
| `start_date` / `end_date` | string | Parsed range bounds (`YYYY-MM-DD`) for querying. |
| `assigned_to` | string | Assignee's display name (or empty). |
| `created_by` | string | Author's display name (stamped from the session, not free text). |
| `created_by_id` | string | Author's user `_id` — used for edit-permission checks. |
| `completed_by` | string | Who marked it complete (auto-stamped). |
| `comment` | string | Long description / notes. |
| `comments` | object[] | Discussion thread — see below. |
| `photo` | string | Optional inline image as a `data:` URI. |
| `delete_requested` | bool | Set when a non-admin requests deletion. |
| `delete_requested_by` | string | Who requested it. |
| `delete_requested_reason` | string | Optional reason. |
| `delete_requested_at` | string | ISO timestamp of the request. |
| `created_at` | datetime | Creation timestamp (UTC). |

**`comments[]` element**

| Field | Type | Notes |
|---|---|---|
| `author` | string | Commenter's display name (from session). |
| `text` | string | Comment body. |
| `timestamp` | string | ISO timestamp; also the delete key for a comment. |

---

## `activity`

Append-only audit log — one document per auditable action (login/logout, create/edit
task, status change, comment, delete request/approve, user management, password change).

| Field | Type | Notes |
|---|---|---|
| `_id` | ObjectId | Primary key. |
| `ts` | datetime | When it happened (UTC). |
| `user_id` / `user_name` / `user_role` | string | Who performed the action. |
| `user_departments` | string[] | Actor's departments at the time. |
| `action` | string | e.g. `login`, `create_task`, `status_change`, `request_delete`, `delete_task`, `comment`, `create_user`, `edit_user`, `delete_user`, `change_password`. |
| `target_type` | string | `task`, `user`, or `session`. |
| `target_id` | string | Affected task/user id (if any). |
| `target_title` | string | Human-readable target (task title or username). |
| `task_departments` | string[] | Departments of the affected task. |
| `depts` | string[] | Union of actor + task departments — **the field managers are scoped on**. |
| `detail` | string | Human-readable summary shown in the Activity Log. |

**Visibility:** admin sees all entries; a manager sees entries whose `depts` intersect
their own departments, plus their own actions; supervisors/normal staff have no access.
