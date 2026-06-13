# Railway Volume 용량·백업 가이드

YejinSaem은 Railway Volume(`/data`)에 **SQLite DB**와 **업로드 사진**을 저장합니다.  
무료 플랜 Volume은 용량이 작아(보통 1GB 전후) 사진이 쌓이면 금방 찹니다.

## 무엇을 백업해야 하나?

| 항목 | 경로 | 필수? | 설명 |
|------|------|-------|------|
| **DB** | `/data/yejinsaem.db` | **필수** | 학부모, 제출, **피드백 텍스트**, 이력 |
| 사진 | `/data/uploads/` | 선택 | 워크시트 원본. 발송 후 삭제해도 피드백은 DB에 남음 |

### 권장 백업 위치 (무료)

Mac 로컬 폴더에 주기적으로 저장하세요.

```text
~/Documents/YejinSaem-backup/
  yejinsaem-2026-05-25.db
  yejinsaem-2026-06-01.db
```

iCloud Drive·Google Drive에 같은 폴더를 두어도 됩니다.  
GitHub에는 DB·사진을 올리지 마세요 (개인정보·용량).

### 백업 방법

1. 관리자 페이지 → **학부모** 탭 → 하단 **「DB 백업 다운로드」**
2. 받은 `yejinsaem-backup-YYYY-MM-DD.db`를 `YejinSaem-backup` 폴더에 보관

월 1회, 또는 대량 학부모 등록·발송 작업 전후에 권장합니다.

## 용량이 99%일 때

### 1) 관리자에서 용량 정리 (권장)

**학부모** 탭 하단 → **「용량 정리」**

- **발송 완료** 제출의 사진 삭제 (피드백·이력은 DB 유지)
- DB에 연결되지 않은 **고아 사진** 삭제
- SQLite **VACUUM** (DB 파일 축소)

대기 중·미발송 제출 사진은 건드리지 않습니다.

### 2) API로 직접 호출

```bash
# 상태
curl -H "Authorization: Bearer <ADMIN_PASSWORD>" \
  https://<도메인>/admin/storage/status

# 정리
curl -X POST -H "Authorization: Bearer <ADMIN_PASSWORD>" \
  -H "Content-Type: application/json" \
  -d '{"remove_sent_photos":true,"remove_orphans":true,"vacuum_database":true}' \
  https://<도메인>/admin/storage/cleanup
```

### 3) 그래도 부족할 때

- 오래된 **이력**에서 불필요한 제출을 **제출 삭제**로 지우기
- Volume 용량 업그레이드는 유료이므로, **발송 완료 후 사진 정리**를 주기적으로 실행하는 것이 무료 운영의 핵심입니다

## 예방

- 피드백 **발송 완료** 후 주기적으로 **용량 정리** 실행
- DB 백업은 정리 **전에** 받기
- 같은 사진을 여러 번 업로드하지 않기

## 복구

백업 DB를 Volume에 다시 올리려면 Railway에서 파일 교체가 필요합니다.  
일상 복구는 **백업 DB 다운로드본을 안전한 곳에 보관**하는 것으로 충분합니다.
