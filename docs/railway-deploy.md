# Railway 배포 가이드

YejinSaem은 **저장소 루트**에서 배포해야 합니다. (`backend/`만 Root로 두면 `frontend/`가 빠져 관리자 화면이 안 뜹니다.)

## 1. Railway 프로젝트 만들기

1. [Railway](https://railway.com/) 로그인
2. **New Project** → **Deploy from GitHub repo** → `YejinSaem` 선택
3. **Settings** → **Root Directory** 를 **비워 두세요** (`frontend` 로 두면 빌드 실패)
4. GitHub에 `Dockerfile`, `railway.toml`, 루트 `requirements.txt` 가 **푸시**되어 있어야 합니다.
5. 빌드는 **Dockerfile** 로 진행됩니다 (Railpack Python 미지원 오류 방지).

### `railpack process exited` / `Script start.sh not found` 가 나올 때

- 원인: Railpack이 Python 프로젝트를 못 찾거나, Root Directory가 잘못됨, 또는 `Dockerfile` 미푸시
- 조치: Root Directory 비우기 → `Dockerfile`·`railway.toml` 커밋·푸시 → **Redeploy**

## 2. Volume (DB + 업로드 사진 유지)

Railway 기본 디스크는 재배포 시 초기화될 수 있습니다. Volume을 붙이세요.

1. 서비스 → **Volumes** → **Add Volume**
2. 마운트 경로: `/data`
3. **Variables** 에 추가:

```env
DATABASE_URL=sqlite:////data/yejinsaem.db
UPLOAD_DIR=/data/uploads
```

Volume 없이 테스트만 할 경우 변수 생략 가능 (재배포 시 데이터 삭제됨).

## 3. 환경 변수

Railway **Variables** 탭에 `backend/.env` 와 동일하게 설정 (값은 Railway에만 넣고 Git에는 올리지 않음):

| 변수 | 필수 | 설명 |
|------|------|------|
| `ANTHROPIC_API_KEY` | 예 | Claude 피드백 |
| `SOLAPI_API_KEY` | 예 | 친구톡 발송 |
| `SOLAPI_API_SECRET` | 예 | |
| `SOLAPI_PF_ID` | 예 | `KA01PF...` |
| `SOLAPI_SENDER_PHONE` | 예 | 발신번호 |
| `ADMIN_PASSWORD` | 예 | 관리자 API·대시보드 |
| `SOLAPI_SENDER_KEY` | 선택 | 구버전 호환 |
| `DATABASE_URL` | Volume 사용 시 | `sqlite:////data/yejinsaem.db` |
| `UPLOAD_DIR` | Volume 사용 시 | `/data/uploads` |

`KAKAO_CHANNEL_SECRET` 은 오픈빌더 연동 시 **넣지 않아도 됩니다.**

`PORT` 는 Railway가 자동 주입합니다. 직접 설정하지 마세요.

## 4. 공개 URL

1. 서비스 → **Settings** → **Networking** → **Generate Domain**
2. 예: `https://yejinsaem-production.up.railway.app`

확인:

- 관리자: `https://<도메인>/`
- 헬스: `https://<도메인>/health`
- API 문서: `https://<도메인>/docs`

## 5. 카카오 오픈빌더 스킬 URL

챗봇 관리자센터 → 스킬 → Endpoint URL:

```text
https://<Railway-도메인>/kakao/webhook
```

스킬 테스트·배포 후 채널에서 사진 제출을 시험하세요.

## 6. 로컬과 병행

- 로컬 개발: `cd backend && python main.py` (localhost:8000)
- 카카오 연동: Railway URL만 오픈빌더에 등록 (ngrok 불필요)

## 문제 해결

| 증상 | 확인 |
|------|------|
| 502 / 헬스 실패 | Deploy 로그에서 `uvicorn` 기동 여부 |
| 대시보드 404 | Root Directory가 `backend` 로만 잡혀 있지 않은지 |
| 제출·사진 사라짐 | Volume + `DATABASE_URL` / `UPLOAD_DIR` |
| Volume 99% 용량 | [railway-volume-backup.md](./railway-volume-backup.md) — 학부모 탭 **용량 정리** |
| 카카오 401 | `KAKAO_CHANNEL_SECRET` 이 Railway에 남아 있지 않은지 |
