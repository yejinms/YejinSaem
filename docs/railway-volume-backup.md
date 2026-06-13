# Railway Volume 용량·백업 가이드

YejinSaem은 Railway Volume(`/data`)에 **SQLite DB**와 **업로드 사진**을 저장합니다.  
무료 Volume(약 1GB)은 **사진** 때문에 금방 찹니다.

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
