# Remaining Feature Development Design Document

> **Summary**: Technical design for stabilizing YejinSaem's Kakao submission, admin review, feedback generation, and resend workflow.
>
> **Project**: YejinSaem
> **Version**: 0.1
> **Author**: Codex
> **Date**: 2026-05-22
> **Status**: Draft
> **Planning Doc**: [remaining-feature-development.plan.md](../../01-plan/features/remaining-feature-development.plan.md)

---

## 1. Overview

### 1.1 Design Goals

This design keeps the current small FastAPI plus static HTML architecture and focuses on closing operational gaps without introducing a new frontend framework or major data model migration.

Primary goals:

- Keep every stored submission attached to a valid registered parent.
- Let admins fix parent contact information without direct database edits.
- Let admins retry message sends after Solapi or configuration failures.
- Protect admin APIs and dashboard with a minimal shared credential.
- Validate uploaded images before storing or processing them.
- Add enough tests and documentation to make the app reproducible from a fresh checkout.

### 1.2 Design Principles

- Preserve existing structure unless a change directly supports the planned workflow.
- Prefer explicit endpoint behavior over hidden side effects.
- Treat external service calls as unreliable and retryable.
- Keep auth simple for phase 1, but make unauthenticated access impossible when configured.
- Keep tests focused on workflow contracts, not visual implementation details.

---

## 2. Architecture

### 2.1 Component Diagram

```text
+-------------------------+
| Kakao Open Builder     |
+-----------+-------------+
            |
            | POST /kakao/webhook
            v
+-------------------------+       +------------------+
| backend/routers/kakao.py| ----> | uploads/         |
+-----------+-------------+       +------------------+
            |
            v
+-------------------------+       +------------------+
| SQLAlchemy models       | ----> | SQLite/Postgres  |
| Parent, Submission      |       | via DATABASE_URL |
+-----------+-------------+       +------------------+
            ^
            |
+-----------+-------------+       +------------------+
| frontend/index.html     | ----> | /admin APIs      |
| Admin dashboard         |       | admin.py         |
+-----------+-------------+       +------------------+
            |
            +---- generate ----> services/claude_service.py
            |
            +---- approve/retry -> services/kakao_service.py -> Solapi
```

### 2.2 Data Flow

#### Registered Kakao Photo Submission

```text
Kakao webhook payload
-> validate optional Kakao secret
-> extract kakao_user_id
-> find Parent by kakao_user_id
-> if missing: return registration-needed Kakao response, no Submission insert
-> extract image URL
-> download image
-> validate downloaded file metadata
-> create Submission(parent_id, photo_path, level, status="pending")
-> return confirmation response
```

#### Admin Feedback Flow

```text
Admin opens pending submission
-> choose level/stage/instruction
-> POST /admin/submissions/{id}/generate
-> Claude generates feedback_draft
-> status = "generated"
-> Admin edits feedback
-> PUT /admin/submissions/{id}/approve
-> Solapi send attempted
-> success: status = "sent"
-> failure: status = "approved", feedback preserved, retry available
```

#### Parent Update Flow

```text
Admin opens parent edit modal
-> edits phone/child/age/level
-> PUT /admin/parents/{id}
-> API validates level and phone shape
-> parent record updates
-> UI refreshes parent list and history
```

### 2.3 Dependencies

| Component | Depends On | Purpose |
|-----------|------------|---------|
| `backend/main.py` | FastAPI middleware, routers | App composition, static file serving, CORS/auth integration point |
| `backend/database.py` | SQLAlchemy | Parent and Submission persistence |
| `backend/routers/kakao.py` | `Parent`, `Submission`, `httpx`, `aiofiles` | Kakao webhook intake and image download |
| `backend/routers/admin.py` | `Parent`, `Submission`, Claude service, Kakao service | Admin workflow APIs |
| `backend/services/claude_service.py` | Anthropic SDK | Vision-based feedback generation |
| `backend/services/kakao_service.py` | Requests, Solapi credentials | Message delivery |
| `frontend/index.html` | Browser fetch API | Admin dashboard |
| tests | FastAPI TestClient, pytest, monkeypatch | Workflow verification |

---

## 3. Data Model

### 3.1 Current Entities

```python
class Parent:
    id: int
    kakao_user_id: str
    phone_number: str | None
    child_name: str
    child_age: int | None
    level: "표현력" | "초등기초" | "초등심화"
    created_at: datetime

class Submission:
    id: int
    parent_id: int
    photo_path: str | None
    level: str | None
    stage: int | None
    extra_instruction: str | None
    feedback_draft: str | None
    status: "pending" | "generated" | "approved" | "sent"
    created_at: datetime
    updated_at: datetime
```

### 3.2 Data Model Decisions

No required schema migration is planned for Phase 1. The existing `Submission.parent_id nullable=False` rule is kept and the webhook is changed to avoid inserting submissions for unregistered users.

Optional future fields, if operational audit detail becomes necessary:

- `Submission.send_error`: last Solapi error body
- `Submission.sent_at`: timestamp for successful send
- `Submission.generated_at`: timestamp for AI generation

These are intentionally deferred to avoid migration complexity until needed.

### 3.3 Entity Relationships

```text
[Parent] 1 ---- N [Submission]

Parent.kakao_user_id is the external identity used by Kakao webhook intake.
Parent.phone_number is the delivery target used by Solapi Friend Talk.
```

### 3.4 State Machine

```text
pending
  -> generated       after Claude feedback generation

generated
  -> sent            after successful Solapi send
  -> approved        after failed Solapi send with feedback preserved

approved
  -> sent            after retry succeeds
  -> approved        after retry fails again

sent
  -> terminal        no further send action in phase 1
```

Invalid transitions:

- `pending -> sent` without feedback text
- any state -> `generated` without photo and parent
- any state -> `sent` without parent phone number

---

## 4. API Specification

### 4.1 Admin Auth Contract

When `ADMIN_PASSWORD` is set, all `/admin/*` endpoints require:

```http
Authorization: Bearer <ADMIN_PASSWORD>
```

If `ADMIN_PASSWORD` is unset, local development may allow unauthenticated requests. Production documentation must require setting it.

Frontend storage:

- Store token in `sessionStorage` under `yejinsaem_admin_token`.
- Add the `Authorization` header in the shared `api()` helper.
- Show a compact password prompt if a request returns `401`.

### 4.2 Endpoint List

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/kakao/webhook` | Receive Kakao message/image payload | Kakao secret if configured |
| GET | `/admin/submissions` | List submissions, optional `status` filter | Required |
| GET | `/admin/submissions/{submission_id}` | Get submission detail | Required |
| POST | `/admin/submissions/upload` | Admin direct upload for parent | Required |
| POST | `/admin/submissions/{submission_id}/generate` | Generate feedback draft | Required |
| PUT | `/admin/submissions/{submission_id}/approve` | Save final feedback and attempt send | Required |
| POST | `/admin/submissions/{submission_id}/retry-send` | Retry sending existing feedback | Required |
| GET | `/admin/parents` | List parents | Required |
| POST | `/admin/parents` | Create or update parent by Kakao user ID | Required |
| GET | `/admin/parents/{parent_id}` | Get parent detail | Required |
| PUT | `/admin/parents/{parent_id}` | Update parent profile, including phone number | Required |
| GET | `/admin/parents/{parent_id}/history` | Get parent submission history | Required |
| GET | `/parents/{kakao_user_id}/profile` | Parent profile lookup | Public for now |
| GET | `/parents/{kakao_user_id}/submissions` | Parent submission history, sent feedback only | Public for now |

### 4.3 Request and Response Changes

#### `PUT /admin/parents/{parent_id}`

Request:

```json
{
  "phone_number": "01012345678",
  "child_name": "민준",
  "child_age": 8,
  "level": "표현력"
}
```

Response:

```json
{
  "id": 1,
  "kakao_user_id": "kakao-user-id",
  "phone_number": "01012345678",
  "child_name": "민준",
  "child_age": 8,
  "level": "표현력"
}
```

#### `POST /admin/submissions/{submission_id}/retry-send`

Request:

```json
{
  "feedback_text": "Optional edited feedback override"
}
```

Response on success:

```json
{
  "id": 10,
  "status": "sent",
  "message": "피드백이 성공적으로 전송되었습니다.",
  "kakao_response": {}
}
```

Response on send failure:

```json
{
  "detail": "피드백은 저장되었지만 카카오 전송에 실패했습니다: ..."
}
```

Implementation note: the retry endpoint should reuse the same internal send helper as approve, so approve and retry do not drift.

#### `POST /kakao/webhook`

Unregistered user behavior:

```json
{
  "version": "2.0",
  "template": {
    "outputs": [
      {
        "simpleText": {
          "text": "아직 등록된 학부모 정보가 없어요. 선생님께 카카오 사용자 ID를 알려주시면 등록 후 피드백을 받을 수 있어요."
        }
      }
    ]
  }
}
```

No `Submission` row is created for unregistered users.

### 4.4 Validation Rules

Parent:

- `kakao_user_id`: required for create; not editable through `PUT /admin/parents/{id}` in phase 1.
- `phone_number`: optional, but if present must contain only digits after removing hyphen and spaces.
- `child_name`: required on create; non-empty if updated.
- `child_age`: optional; if present between 5 and 15.
- `level`: one of `표현력`, `초등기초`, `초등심화`.

Submission generate:

- `photo_path` must exist.
- parent must exist.
- `stage` between 1 and 10.
- `level` valid.

Image upload/download:

- Allowed extensions: `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`.
- Allowed content types: `image/jpeg`, `image/png`, `image/gif`, `image/webp`.
- Maximum size: 10 MB.
- Stored filename remains UUID-based.

---

## 5. UI/UX Design

### 5.1 Admin Screens

Existing tabs remain:

```text
+------------------------------------------------+
| 예진샘 관리자                                  |
+------------------------------------------------+
| 대기 목록 | 이력 | 학부모 관리                 |
+------------------------------------------------+
```

### 5.2 Component Changes

| Area | Current | Change |
|------|---------|--------|
| Shared API helper | Sends JSON requests without auth | Add optional `Authorization` header from `sessionStorage` |
| Auth prompt | None | Add compact modal or browser prompt on first `401` |
| Parent list | Click opens history only | Add separate edit button per parent; keep row click for history |
| Parent modal | Create only | Reuse for edit mode with `PUT /admin/parents/{id}` |
| Submission modal | Approve sends feedback | For `approved`, show retry button using existing feedback |
| Pending list | Shows all non-sent submissions | Keep behavior; make `approved` visually actionable |
| Direct upload | Backend only | Optional phase 4 UI: parent picker plus file input |

### 5.3 Parent Edit Interaction

```text
Parents tab
-> parent row shows history affordance and edit button
-> edit button opens existing parent modal
-> Kakao user ID readonly
-> phone/child/age/level editable
-> save calls PUT /admin/parents/{id}
-> list refreshes
```

### 5.4 Approved Retry Interaction

```text
Submission status = approved
-> modal shows preserved feedback
-> primary action: "다시 전송"
-> optional edit before retry
-> POST /admin/submissions/{id}/retry-send
```

### 5.5 Auth Interaction

```text
Admin opens dashboard
-> API request returns 401
-> UI asks for admin password
-> saves password to sessionStorage
-> retries original request
```

No persistent localStorage for the admin password in phase 1.

---

## 6. Error Handling

| Condition | HTTP/State | Message | Handling |
|-----------|------------|---------|----------|
| Missing admin credential | 401 | 관리자 인증이 필요합니다. | Frontend prompts for password and retries |
| Wrong admin credential | 401 | 관리자 비밀번호가 올바르지 않습니다. | Clear session token and prompt again |
| Unregistered Kakao user | 200 Kakao response | 등록 안내 message | No DB insert |
| Kakao payload lacks user ID | 200 Kakao response | 메시지를 처리할 수 없었어요. 다시 시도해 주세요. | Log warning |
| Kakao payload lacks image | 200 Kakao response | 사진 요청 message | No DB insert unless registered text tracking is later needed |
| Image download fails | 200 Kakao response | 사진을 불러오지 못했어요. 다시 보내주세요. | No submission insert |
| Invalid upload file | 400 | 지원하지 않는 이미지 형식입니다. | UI toast |
| Missing phone number on send | 400 | 전화번호 등록 필요 | UI tells admin to edit parent |
| Solapi send failure | 502 | Feedback saved, send failed | Status remains `approved`, retry available |
| Claude failure | 500 | Failed to generate feedback | Status unchanged, log error |

---

## 7. Security Considerations

- [ ] Add admin auth dependency to `/admin` router.
- [ ] Use constant-time comparison for admin token checks.
- [ ] Keep `ADMIN_PASSWORD` out of source control; `.env` remains ignored.
- [ ] Avoid logging full admin token, Solapi secret, or Anthropic key.
- [ ] Validate upload content type and size before writing unbounded files.
- [ ] Keep uploaded image filenames UUID-based.
- [ ] Consider restricting CORS origins before public deployment.
- [ ] Add Kakao webhook shared-secret validation if supported by the configured Kakao integration.

Implementation detail for admin auth:

```python
import hmac
from fastapi import Header

def verify_admin(authorization: str | None = Header(default=None)):
    password = os.getenv("ADMIN_PASSWORD")
    if not password:
        return
    expected = f"Bearer {password}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="관리자 인증이 필요합니다.")
```

---

## 8. Test Plan

### 8.1 Test Tooling

Add to `backend/requirements.txt` or a separate dev requirements file:

- `pytest`
- `httpx` is already present and required by FastAPI TestClient stack

Tests should use:

- temporary SQLite database URL
- temporary upload directory
- monkeypatched `generate_feedback`
- monkeypatched `send_feedback_message`

### 8.2 API Smoke Tests

| ID | Target | Scenario | Expected |
|----|--------|----------|----------|
| T-01 | Health | `GET /health` | `200`, service ok |
| T-02 | Parent create | `POST /admin/parents` | parent includes phone number |
| T-03 | Parent update | `PUT /admin/parents/{id}` with phone number | response and DB update phone |
| T-04 | Webhook unregistered | Kakao payload with unknown user | `200` Kakao response, no submission row |
| T-05 | Webhook registered text-only | Known user without image | photo request response, no invalid submission |
| T-06 | Webhook registered image | Known user with mocked image download | pending submission created |
| T-07 | Generate missing photo | Generate on submission without photo | `400` |
| T-08 | Generate success | Mock Claude | status `generated`, draft stored |
| T-09 | Approve missing phone | Parent without phone | `400`, status unchanged |
| T-10 | Approve send failure | Mock Solapi failure | `502`, status `approved`, feedback preserved |
| T-11 | Retry send success | Existing `approved` submission | status `sent` |
| T-12 | Admin auth | `ADMIN_PASSWORD` set, no header | `401` |
| T-13 | Upload validation | Non-image upload | `400` |

### 8.3 Manual Browser Checks

- Admin password prompt appears when required.
- Parent create and edit both work.
- Approved submission shows retry action.
- Sent submission disables send actions.
- Pending list and history refresh after actions.

---

## 9. Implementation Guide

### 9.1 Implementation Order

1. [ ] Add shared constants/helpers for valid levels, phone normalization, and image validation.
2. [ ] Fix `kakao.py` unregistered and no-image submission creation behavior.
3. [ ] Extend `ParentUpdate` and parent API responses with `phone_number`.
4. [ ] Extract send logic in `admin.py` into a helper used by approve and retry.
5. [ ] Add `POST /admin/submissions/{submission_id}/retry-send`.
6. [ ] Add minimal admin auth dependency and wire it into the admin router.
7. [ ] Update `frontend/index.html` API helper, auth prompt, parent edit UI, and retry button.
8. [ ] Add upload validation to admin upload and Kakao download paths.
9. [ ] Add tests for the core workflow.
10. [ ] Add README setup and operation instructions.

### 9.2 File-Level Change Plan

| File | Planned Changes |
|------|-----------------|
| `backend/routers/kakao.py` | Reject unregistered users without DB insert; validate downloaded images; improve response text |
| `backend/routers/admin.py` | Add phone update; add auth dependency; add retry endpoint; refactor send helper; validate upload |
| `backend/database.py` | No required phase-1 schema change |
| `backend/services/kakao_service.py` | Keep API client; optionally improve parameter naming from `kakao_user_id` to `phone_number` |
| `backend/main.py` | Potential CORS tightening later; no phase-1 required change except auth import if centralized |
| `frontend/index.html` | Add session auth; add parent edit mode; add retry UI; optional direct upload UI |
| `backend/requirements.txt` | Add `pytest` if tests are committed in this repo |
| `README.md` | New setup and operations guide |
| `backend/tests/` or `tests/` | New smoke/API tests |

### 9.3 Internal Helper Design

Recommended helpers:

```python
VALID_LEVELS = ["표현력", "초등기초", "초등심화"]
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
ALLOWED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
```

```python
def normalize_phone_number(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.replace("-", "").replace(" ", "")
    if normalized and not normalized.isdigit():
        raise HTTPException(status_code=400, detail="전화번호는 숫자만 입력해주세요.")
    return normalized or None
```

```python
def send_submission_feedback(submission: Submission, feedback_text: str, db: Session) -> dict:
    # shared approve/retry behavior
```

### 9.4 Acceptance Checklist

- [ ] `FR-01` through `FR-12` in the plan are either implemented or explicitly deferred.
- [ ] API tests T-01 through T-13 pass.
- [ ] `python -m compileall backend` passes.
- [ ] README can be followed from a clean environment.
- [ ] `.pdca-status.json` moves to `do` after implementation begins.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-05-22 | Initial technical design for remaining feature development | Codex |
