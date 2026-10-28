# 고객 시트 → 예진샘 웹 자동 등록

두 Google Sheet 프로젝트에 각각 `CustomerImport.gs`를 추가하고, 각 함수에 5분 간격 시간 기반 트리거를 설정한다. Sheet API/커넥터로 추가한 행도 시간 트리거가 감지한다. 발송 트리거와 독립적이며 메시지를 보내지 않는다.

| 시트 프로젝트 | 추가 파일 | 실행 함수 |
| --- | --- | --- |
| 매주 3단어 `수신자 리스트` | `weekly-words/CustomerImport.gs` | `syncWeeklyCustomersToWeb` |
| 8주 완성 `8주완성 고객관리` | `eight-week/CustomerImport.gs` | `syncEightWeekCustomersToWeb` |

설정:

1. Railway 운영 환경에 임의 생성한 긴 비밀값을 `CUSTOMER_SHEET_IMPORT_TOKEN`으로 저장한다.
2. 두 Apps Script 프로젝트의 Script Properties에 동일한 `CUSTOMER_SHEET_IMPORT_TOKEN`을 저장한다. 각각 `WEB_API_BASE=https://yejinsaem-production.up.railway.app`도 설정한다.
3. 각 프로젝트에 파일을 추가한 후 함수를 한 번 수동 실행하여 권한을 부여하고 실행 로그의 `created`/`updated`/`skipped`를 확인한다.
4. 두 함수에 각각 5분 간격 시간 기반 트리거를 설정한다. 기존 발송, 온보딩, 잔여 횟수 트리거는 건드리지 않는다.

각 스크립트는 고객 구매 필드만 읽어 변경 시 전체 목록을 재조정한다. 매주 3단어의 진행/발송 기록은 보내지 않는다. 8주 완성의 사용완료/남은횟수(J/K열)는 변경 감지에서 제외한다. 이미 등록된 구매는 식별값 기준으로 건너뛰며, 웹 DB의 첨삭 사용 이력을 덮어쓰지 않는다. 실행 오류가 나면 성공 해시를 저장하지 않아 다음 트리거에서 다시 시도한다.

현재 매주 3단어 시트의 529행은 연락처에 숫자가 없는 보류 행이다. 동기화에서 제외하고 실행 로그에 행 번호를 남긴다. 정상 연락처를 입력하면 다음 실행에서 등록된다.
