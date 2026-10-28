/** Separate five-minute trigger in the 매주 3단어 spreadsheet project. */
function syncWeeklyCustomersToWeb() {
  const props = PropertiesService.getScriptProperties();
  const base = String(props.getProperty('WEB_API_BASE') || '').replace(/\/$/, '');
  const token = props.getProperty('CUSTOMER_SHEET_IMPORT_TOKEN');
  if (!base || !token) throw new Error('WEB_API_BASE / CUSTOMER_SHEET_IMPORT_TOKEN 설정이 필요합니다.');
  const book = SpreadsheetApp.openById('1JTWBMFEv2JLGl6ySulhr2bXON5DXdts2Djvn3vR8duo');
  const sheet = book.getSheetByName('수신자 리스트');
  if (!sheet) throw new Error('수신자 리스트 탭이 없습니다.');
  const head = sheet.getRange(1, 1, 1, 6).getDisplayValues()[0];
  if (head[0] !== '구매자 ID' || head[1] !== '수신 연락처' || head[4] !== '채널' || head[5] !== '상품') {
    throw new Error('수신자 리스트 열 구성이 달라졌습니다.');
  }
  const last = sheet.getLastRow();
  if (last < 2) return;
  const source = sheet.getRange(2, 1, last - 1, 6).getDisplayValues();
  const rows = [];
  const ignored = [];
  source.forEach(function(row, index) {
    if (!row[0] && !row[1]) return;
    if (!row[0] || !/[0-9]/.test(row[1]) || !row[5]) {
      ignored.push(index + 2);
      return;
    }
    // C/D are progress and notes, not customer identity.
    rows.push([row[0], row[1], '', '', row[4], row[5]].map(String));
  });
  if (!rows.length) return;
  if (ignored.length) console.log('연락처 또는 필수 값이 없어 제외한 시트 행: ' + ignored.join(', '));
  const digest = Utilities.base64EncodeWebSafe(Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256, JSON.stringify(rows)));
  if (props.getProperty('CUSTOMER_IMPORT_WEEKLY_HASH') === digest) return;
  const response = UrlFetchApp.fetch(base + '/customer-sheet/weekly', {
    method: 'post', contentType: 'application/json',
    headers: {Authorization: 'Bearer ' + token},
    payload: JSON.stringify({rows: rows}), muteHttpExceptions: true,
  });
  if (response.getResponseCode() !== 200) {
    throw new Error('매주 3단어 고객 가져오기 실패: HTTP ' + response.getResponseCode() + ' ' + response.getContentText().slice(0, 500));
  }
  props.setProperty('CUSTOMER_IMPORT_WEEKLY_HASH', digest);
  console.log('매주 3단어 고객 가져오기: ' + response.getContentText());
}
