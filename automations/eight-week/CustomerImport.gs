/** Separate five-minute trigger in the 8주완성 고객관리 spreadsheet project. */
function syncEightWeekCustomersToWeb() {
  const props = PropertiesService.getScriptProperties();
  const base = String(props.getProperty('WEB_API_BASE') || '').replace(/\/$/, '');
  const token = props.getProperty('CUSTOMER_SHEET_IMPORT_TOKEN');
  if (!base || !token) throw new Error('WEB_API_BASE / CUSTOMER_SHEET_IMPORT_TOKEN 설정이 필요합니다.');
  const book = SpreadsheetApp.openById('1MwUCM3EmEPQLqBDCnyS2046vmURDqXb8MP2uEWxJbpw');
  const sheet = book.getSheetByName('8주완성 고객관리');
  if (!sheet) throw new Error('8주완성 고객관리 탭이 없습니다.');
  const head = sheet.getRange(1, 1, 1, 6).getDisplayValues()[0];
  if (head[0] !== '구매자명' || head[1] !== '연락처' || head[2] !== '교재단계' || head[4] !== '구매유형') {
    throw new Error('8주완성 고객관리 열 구성이 달라졌습니다.');
  }
  const last = sheet.getLastRow();
  if (last < 2) return;
  const source = sheet.getRange(2, 1, last - 1, 15).getDisplayValues();
  const rows = [];
  const identity = [];
  source.forEach(function(row, index) {
    if (!row[0] && !row[1]) return;
    if (!row[0] || !row[1] || !row[2] || !row[4] || !row[5]) {
      throw new Error('8주 완성 구매 행의 필수 값이 없습니다: ' + (index + 2));
    }
    rows.push(row.map(String));
    // J/K are updated by feedback balance sync. Exclude them from the change key.
    identity.push(row.filter(function(_, col) { return col !== 9 && col !== 10; }));
  });
  if (!rows.length) return;
  const digest = Utilities.base64EncodeWebSafe(Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256, JSON.stringify(identity)));
  if (props.getProperty('CUSTOMER_IMPORT_WORKBOOK_HASH') === digest) return;
  const response = UrlFetchApp.fetch(base + '/customer-sheet/workbook', {
    method: 'post', contentType: 'application/json',
    headers: {Authorization: 'Bearer ' + token},
    payload: JSON.stringify({rows: rows}), muteHttpExceptions: true,
  });
  if (response.getResponseCode() !== 200) {
    throw new Error('8주 완성 고객 가져오기 실패: HTTP ' + response.getResponseCode() + ' ' + response.getContentText().slice(0, 500));
  }
  props.setProperty('CUSTOMER_IMPORT_WORKBOOK_HASH', digest);
  console.log('8주 완성 고객 가져오기: ' + response.getContentText());
}
