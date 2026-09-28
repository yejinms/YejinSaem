/**
 * Add this file to the existing 8주완성 고객관리 Apps Script project.
 * In the existing expiry reminder function, call syncEightWeekBalancesFromWeb()
 * before reading customer rows.
 * Script Properties: WEB_API_BASE (e.g. https://...up.railway.app), WEB_ADMIN_PASSWORD.
 * This script does not send messages; the existing dailyExpiryCheck remains the sender.
 */
function syncEightWeekBalancesFromWeb() {
  const columns = {phone: 2, level: 3, type: 5, purchaseDate: 6,
                   total: 9, used: 10, remain: 11, lastReminder: 14};
  const props = PropertiesService.getScriptProperties();
  const base = String(props.getProperty('WEB_API_BASE') || '').replace(/\/$/, '');
  const password = props.getProperty('WEB_ADMIN_PASSWORD');
  if (!base || !password) throw new Error('WEB_API_BASE / WEB_ADMIN_PASSWORD 설정이 필요합니다.');

  const response = UrlFetchApp.fetch(base + '/admin/workbook-purchases/sheet-balances', {
    method: 'get',
    headers: { Authorization: 'Bearer ' + encodeURIComponent(password) },
    muteHttpExceptions: true,
  });
  if (response.getResponseCode() !== 200) {
    throw new Error('웹 첨삭권 잔여 횟수 조회 실패: HTTP ' + response.getResponseCode());
  }

  const balances = JSON.parse(response.getContentText());
  const byKey = new Map();
  for (const item of balances) {
    const key = [digits_(item.phone_number), item.workbook_level, item.pass_type, item.purchase_date].join('|');
    if (byKey.has(key)) throw new Error('웹에 동일 구매 식별값이 중복됩니다.');
    byKey.set(key, item);
  }

  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName('8주완성 고객관리');
  if (!sheet) throw new Error('8주완성 고객관리 시트를 찾을 수 없습니다.');
  const sheetTimezone = spreadsheet.getSpreadsheetTimeZone();
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return;
  const rows = sheet.getRange(2, 1, lastRow - 1, columns.lastReminder).getValues();
  const seen = new Set();
  const updates = [];
  const remainFormula = '=RC[' + (columns.total - columns.remain) + ']-RC[' + (columns.used - columns.remain) + ']';
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    const phone = row[columns.phone - 1];
    if (!phone) continue;
    const purchaseDate = row[columns.purchaseDate - 1];
    if (!(purchaseDate instanceof Date)) continue;
    const bought = Utilities.formatDate(purchaseDate, sheetTimezone, 'yyyy-MM-dd');
    const key = [digits_(phone), row[columns.level - 1], row[columns.type - 1], bought].join('|');
    const item = byKey.get(key);
    if (!item) throw new Error('웹 DB에 없는 시트 구매 행: ' + (i + 2));
    if (seen.has(key)) throw new Error('시트의 구매 행이 중복됩니다: ' + (i + 2));
    seen.add(key);
    if (Number(row[columns.total - 1]) !== Number(item.used_uses) + Number(item.remaining_uses)) {
      throw new Error('웹과 시트의 총횟수가 다릅니다: ' + (i + 2));
    }
    updates.push({row: i + 2, used: item.used_uses});
  }
  for (const item of updates) {
    const usedCell = sheet.getRange(item.row, columns.used);
    if (Number(usedCell.getValue()) !== Number(item.used)) usedCell.setValue(item.used);
    const remainCell = sheet.getRange(item.row, columns.remain);
    if (!remainCell.getFormula()) remainCell.setFormulaR1C1(remainFormula);
  }
}

function digits_(value) {
  return String(value || '').replace(/\D/g, '');
}
