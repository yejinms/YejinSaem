# Railway Volume 용량·백업 가이드

YejinSaem은 Railway Volume(`/data`)에 **SQLite DB**와 **업로드 사진**을 저장합니다.  
무료 Volume(0.5GB)은 **사진** 때문에 금방 찹니다.

## 무엇을 백업해야 하나?

| 항목 | 용량 | 필수? | 백업 방법 |
|------|------|-------|-----------|
| **사진** | **대부분** | **용량 비우기 전 필수** | 관리자 → **사진 ZIP 백업** |
| DB | 작음 | 권장 | 관리자 → **DB 백업** |

피드백·학부모 정보는 DB에 있습니다.  
**사진을 지우기 전에 ZIP으로 받아 두지 않으면** 워크시트 원본은 복구할 수 없습니다.

## 권장 순서 (무료 운영)

1. **사진 ZIP 백업** 다운로드
2. Mac에 저장: `~/Documents/YejinSaem-backup/photos/yejinsaem-photos-YYYY-MM-DD.zip`
3. (선택) **DB 백업** → `~/Documents/YejinSaem-backup/`
4. **용량 정리** 실행

ZIP 안에는 `manifest.json`(제출 ID·이름·상태)과 `photos/` 폴더가 들어 있습니다.

## 관리자 UI

**학부모** 탭 하단 **저장소 (Railway Volume)**

- **사진 ZIP 백업** — 전체 업로드 사진 일괄 다운로드
- **DB 백업** — 학부모·피드백 DB
- **용량 정리** — 발송 완료 사진·고아 파일 삭제 + DB VACUUM

## API

```bash
# 사진 ZIP
curl -H "Authorization: Bearer <ADMIN_PASSWORD>" \
  -o yejinsaem-photos.zip \
  https://<도메인>/admin/storage/backup/photos

# DB
curl -H "Authorization: Bearer <ADMIN_PASSWORD>" \
  -o yejinsaem.db \
  https://<도메인>/admin/storage/backup/database

# 정리
curl -X POST -H "Authorization: Bearer <ADMIN_PASSWORD>" \
  -H "Content-Type: application/json" \
  -d '{"remove_sent_photos":true,"remove_orphans":true,"vacuum_database":true}' \
  https://<도메인>/admin/storage/cleanup
```

## 백업 저장 위치 (무료)

- Mac **문서/YejinSaem-backup/photos/** — 사진 ZIP
- Mac **문서/YejinSaem-backup/** — DB 파일
- iCloud Drive에 같은 폴더를 두어도 됩니다
- GitHub에는 올리지 마세요 (개인정보·용량)

## 용량이 99%일 때

1. **사진 ZIP 백업** (시간이 걸릴 수 있음)
2. ZIP이 Mac에 잘 저장됐는지 확인
3. **용량 정리**
4. **새로고침**으로 용량 확인

대기 중·미발송 제출 사진은 정리하지 않습니다.

## 350MB R2 자동 백업

Railway **Variables**에 아래 값을 설정하면, 서버 시작 시와 사진 접수 직후 저장소 사용량을 확인합니다.

| 변수 | 값 |
|---|---|
| `AUTO_ARCHIVE_ENABLED` | `true` |
| `R2_ACCOUNT_ID` | Cloudflare 계정 ID |
| `R2_BUCKET` | 비공개 Standard 버킷 이름 |
| `R2_ACCESS_KEY_ID` | 버킷 한정 Object Read & Write 토큰의 Access Key ID |
| `R2_SECRET_ACCESS_KEY` | 위 토큰의 Secret Access Key |

Cloudflare 대시보드에서 **R2 → Create bucket**을 선택하고 `Standard` 저장 클래스로 비공개 버킷을 만듭니다. 이어서 **R2 → Manage API Tokens**에서 해당 버킷에만 적용되는 **Object Read & Write** 자격 증명을 만듭니다. 비밀키는 Railway Variables에만 저장하세요. R2는 무료 10GB를 넘으면 요금이 발생할 수 있습니다. [R2 설정](https://developers.cloudflare.com/r2/get-started/s3/) · [요금](https://developers.cloudflare.com/r2/pricing/)

사진과 DB의 합계가 **350 MB**에 도달하면 사진 ZIP과 일관된 SQLite DB 백업을 만듭니다. 두 파일을 R2에 업로드한 후 R2에서 다시 읽어 SHA-256으로 검증합니다. 모두 일치해야 그 ZIP에 담겼고 이후 변경되지 않은 **발송 완료 사진만** 삭제합니다. 대기 중 사진과 고아 파일은 자동 삭제하지 않습니다. ZIP과 DB 사본은 Railway Volume 밖의 임시 디렉터리에 만들고 실행 후 제거합니다. 업로드가 실패하면 원본 사진을 남기며, 다음 사진 접수 또는 서버 재시작 시 다시 시도합니다.

이 백업 버킷 사용량이 **8GB**를 넘으면 관리자 저장소 화면에 외장하드 이동 안내가 나옵니다. `SLACK_R2_WEBHOOK_URL`에 **#첨삭-사진-백업** 채널의 Slack Incoming Webhook URL을 설정하면 같은 시점에 채널로 한 번 알립니다. 8GB 미만으로 내려간 뒤 다시 8GB에 도달하면 새 알림을 보냅니다. ZIP이나 아동 정보는 Slack으로 전송하지 않습니다. 새 백업을 올리면 **9GB**를 넘는 경우 자동 백업·정리를 멈춥니다. 이때 원본은 Railway에 남으므로, R2 ZIP과 DB 파일을 외장하드로 내려받아 확인한 뒤 R2에서 오래된 세트를 지워 공간을 비우세요. 무료 용량 10GB는 매달 새로 주어지는 공간이 아니라, 보관 중인 데이터의 월평균 사용량 기준입니다. 이 상한은 **해당 버킷만** 계산하므로 같은 Cloudflare 계정의 다른 R2 버킷을 사용하면 전체 사용량을 별도로 확인해야 합니다.

R2 백업이 끝날 때마다 같은 Slack 채널로 사진 ZIP·DB 백업 파일명, 백업 사진 수, 정리된 사진 수를 알립니다. 아동 이름이나 사진 파일 자체는 Slack으로 보내지 않습니다. 350MB 미만에서도 즉시 백업하려면 관리자 인증을 붙여 `POST /admin/storage/archive-now`를 호출하고, 반환된 `run_id`와 `/admin/storage/status`의 `auto_archive` 상태를 비교해 완료 여부를 확인하세요.
