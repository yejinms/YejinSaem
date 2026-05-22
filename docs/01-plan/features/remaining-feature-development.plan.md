# Remaining Feature Development Planning Document

> **Summary**: Stabilize the core Kakao-to-feedback workflow, then add the minimum admin and operational features needed for production use.
>
> **Project**: YejinSaem
> **Version**: 0.1
> **Author**: Codex
> **Date**: 2026-05-22
> **Status**: Draft

---

## 1. Overview

### 1.1 Purpose

YejinSaem currently has the main shape of the product: Kakao webhook intake, uploaded worksheet storage, Claude feedback generation, Solapi Kakao Friend Talk sending, and a single-page admin dashboard. The remaining work is to make that flow reliable enough for real operation and to close the gaps that can block a teacher during daily use.

### 1.2 Background

The current codebase is small and direct:

- FastAPI backend under `backend/`
- SQLAlchemy models in `backend/database.py`
- Admin APIs in `backend/routers/admin.py`
- Kakao webhook intake in `backend/routers/kakao.py`
- Parent-facing APIs in `backend/routers/parents.py`
- Single-file admin UI in `frontend/index.html`

The highest-risk issues are not visual polish. They are workflow blockers: unregistered Kakao users can create invalid submissions, parent phone numbers cannot be edited after creation, admin/webhook authentication is not enforced, and retry/documentation/test coverage are missing.

### 1.3 Related Documents

- Source inspection: current repository files
- Future design document: `docs/02-design/features/remaining-feature-development.design.md`
- Future analysis document: `docs/03-analysis/remaining-feature-development.analysis.md`

---

## 2. Scope

### 2.1 In Scope

- [ ] Fix Kakao webhook handling for unregistered users.
- [ ] Add parent phone number update support in backend and admin UI.
- [ ] Add a resend/retry path for submissions stuck in `approved` after send failure.
- [ ] Add minimal admin authentication using existing `ADMIN_PASSWORD` configuration.
- [ ] Add Kakao webhook request verification using existing `KAKAO_CHANNEL_SECRET` configuration, if the deployed Kakao integration can send a verifiable secret/header.
- [ ] Add upload validation for size, extension, and content type.
- [ ] Add project setup documentation covering environment variables, local run, Kakao, Solapi, and Claude configuration.
- [ ] Add a focused smoke/API test suite for the core workflow.
- [ ] Add basic operational logging around AI generation and message sending failures.

### 2.2 Out of Scope

- Full multi-user admin accounts and role-based access control.
- Major frontend framework migration from single-file HTML to React/Vue.
- Large database migration system unless schema changes require it.
- Payment, subscriptions, or parent self-service onboarding flows.
- Advanced analytics, dashboards, and cohort reporting.
- Full production infrastructure automation.

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | Registered Kakao users can submit worksheet photos and create valid `pending` submissions. | High | Pending |
| FR-02 | Unregistered Kakao users do not create invalid DB rows; the system either rejects with a clear Kakao response or stores a valid registration-needed record. | High | Pending |
| FR-03 | Admin can create parents with Kakao user ID, phone number, child name, child age, and level. | High | Existing, needs verification |
| FR-04 | Admin can edit parent phone number, child name, child age, and level after creation. | High | Partial |
| FR-05 | Admin can generate feedback only for submissions with a valid parent and image. | High | Existing, needs verification |
| FR-06 | Admin can review and edit generated feedback before sending. | High | Existing, needs verification |
| FR-07 | Sending failures preserve edited feedback and expose a retry path. | High | Partial |
| FR-08 | Admin can directly upload a worksheet for a selected parent from the UI. | Medium | Backend only |
| FR-09 | Admin can distinguish `pending`, `generated`, `approved`, and `sent` states clearly in lists and detail views. | Medium | Partial |
| FR-10 | Parent-facing history only exposes sent feedback. | Medium | Existing, needs verification |
| FR-11 | System validates uploaded and downloaded image files before storing or processing. | Medium | Pending |
| FR-12 | Runtime setup is documented enough for a new operator to configure `.env` and start the app. | High | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Reliability | Core workflow can be smoke-tested locally without external APIs by mocking Claude and Solapi. | Automated API tests or documented test commands |
| Security | Admin endpoints are protected by at least password/token-based access control before deployment. | Manual and automated unauthorized request checks |
| Security | Kakao webhook accepts only expected requests when a shared secret is configured. | Manual webhook request checks |
| Data Integrity | No submission row violates required parent linkage rules. | API tests and DB constraint checks |
| Operability | Failed AI generation and failed sends are logged with submission ID and actionable error details. | Log inspection |
| Maintainability | Setup and run instructions exist in README. | Fresh checkout run-through |
| Compatibility | Existing single-file frontend continues to work without a build step. | Browser smoke test |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] Kakao webhook does not crash or create invalid DB records for unregistered users.
- [ ] Parent phone number can be updated through both API and admin UI.
- [ ] A failed send can be retried without regenerating feedback.
- [ ] Admin APIs and dashboard have a minimal authentication mechanism.
- [ ] Upload/download image paths reject obviously invalid files.
- [ ] README includes install, environment, run, and external service setup steps.
- [ ] Core API smoke tests pass locally.
- [ ] Manual browser check confirms the admin flow works end to end with mocked or configured services.

### 4.2 Quality Criteria

- [ ] `python -m compileall backend` succeeds.
- [ ] API smoke tests cover parent create/update, webhook intake, submission list/detail, generation error path, and approve failure/retry path.
- [ ] No secrets are committed.
- [ ] Changes are scoped to existing FastAPI, SQLAlchemy, and vanilla HTML patterns.
- [ ] User-facing Korean copy is clear and operationally useful.

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Kakao Open Builder payload shape differs from current assumptions. | High | Medium | Keep extraction defensive, log unsupported payloads, document required Open Builder settings. |
| Solapi Friend Talk options require a template or different payload fields. | High | Medium | Test with real Solapi sandbox/account before production; preserve response bodies in logs. |
| Minimal admin password is insufficient for public deployment. | High | Medium | Treat password auth as phase-1 hardening only; document need for stronger auth if exposed broadly. |
| Schema changes on SQLite without migrations can break existing local DBs. | Medium | Medium | Prefer code-level fixes that avoid unnecessary schema changes; back up DB before schema changes. |
| External AI/API calls make tests slow or flaky. | Medium | High | Mock `generate_feedback` and `send_feedback_message` in tests. |
| Single-file frontend becomes hard to maintain as admin features grow. | Medium | Medium | Keep UI changes minimal; revisit framework migration only after workflow stabilization. |

---

## 6. Architecture Considerations

### 6.1 Project Level Selection

| Level | Characteristics | Selected |
|-------|-----------------|:--------:|
| **Starter** | Simple structure, static sites | - |
| **Dynamic** | Backend APIs, persistent data, external services | Yes |
| **Enterprise** | Strict layer separation, microservices | - |

This project is a Dynamic-level app because it has a backend, database, static admin UI, external AI service, and external messaging provider. The plan should preserve the current simple architecture while hardening the workflow.

### 6.2 Key Architectural Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| Backend framework | FastAPI / Flask / Django | FastAPI | Already implemented and suitable for webhook/API flow. |
| Data layer | SQLite only / PostgreSQL now / SQLAlchemy-compatible | Keep SQLAlchemy and current SQLite default | Minimal change; can move to PostgreSQL later via `DATABASE_URL`. |
| Frontend | Vanilla HTML / React / Vue | Keep vanilla HTML for now | No build pipeline and current UI is small. |
| Auth phase 1 | No auth / shared admin password / full user accounts | Shared admin password/token | Matches existing `.env.example` and keeps scope small. |
| Test approach | Manual only / pytest API tests / full browser automation | Focused API tests first | Highest value for backend workflow blockers. |
| Unregistered Kakao handling | Store orphan submission / reject with guidance / create pending parent | Reject with clear guidance first | Avoids violating current non-null parent relationship and prevents unusable submissions. |

---

## 7. Implementation Order

### Phase 1: Workflow Blockers

1. Fix unregistered Kakao webhook handling.
2. Add parent phone number update to `ParentUpdate`, `PUT /admin/parents/{parent_id}`, and response payloads.
3. Add admin UI edit path for parent profile fields.
4. Add retry send action for `approved` submissions.

### Phase 2: Security and Validation

1. Add minimal admin auth dependency for `/admin` routes.
2. Add frontend support for supplying the admin credential.
3. Add Kakao webhook shared-secret validation if compatible with deployment.
4. Validate upload file size, extension, and content type.

### Phase 3: Tests and Documentation

1. Add test dependencies and API smoke tests.
2. Mock Claude and Solapi service calls.
3. Add README with local setup and service configuration.
4. Document manual production checklist.

### Phase 4: Nice-to-Have Admin UX

1. Add admin direct-upload UI.
2. Improve status filters and failed-send visibility.
3. Add simple delete/archive action if operationally needed.

---

## 8. Next Steps

1. [ ] Write design document: `docs/02-design/features/remaining-feature-development.design.md`
2. [ ] Implement Phase 1 workflow blockers.
3. [ ] Run local API smoke checks.
4. [ ] Continue PDCA Check with `docs/03-analysis/remaining-feature-development.analysis.md`.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-05-22 | Initial remaining feature development plan | Codex |
