# Remaining Feature Development Do Log

> **Feature**: remaining-feature-development
> **Date**: 2026-05-22
> **Status**: Implementation in progress

## Implementation Scope

This Do phase implements the high-priority workflow stabilization items from the design document:

- Registered-only Kakao submissions
- Parent phone number update
- Send failure preservation and retry
- Minimal admin auth
- Image validation
- Focused API smoke tests
- README setup documentation

## Implementation Checklist

- [x] Add shared validation and auth helpers.
- [x] Fix unregistered Kakao webhook behavior.
- [x] Prevent text-only Kakao messages from creating invalid submissions.
- [x] Validate downloaded Kakao images before storing.
- [x] Validate admin-uploaded images before storing.
- [x] Add parent phone number update support.
- [x] Add retry send endpoint.
- [x] Refactor approve/retry to use one send helper.
- [x] Add frontend admin token support.
- [x] Add frontend parent edit mode.
- [x] Add frontend retry action for approved submissions.
- [x] Add frontend direct image upload and clipboard paste submission creation.
- [x] Add API smoke tests for critical flows.
- [x] Add README setup and operations guide.

## Verification Commands

```bash
python -m compileall backend
python -m pytest backend/tests
```

## Notes

- bkit MCP pre/post write tools are not exposed in this running Codex session, so implementation followed the generated design document directly.
- Admin auth is enabled only when `ADMIN_PASSWORD` is intentionally configured. Placeholder values beginning with `your_` are ignored.
- Kakao webhook secret validation accepts `X-Kakao-Secret` or `X-Kakao-Channel-Secret` when `KAKAO_CHANNEL_SECRET` is intentionally configured.
