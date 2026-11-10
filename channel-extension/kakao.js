// Kakao's private manager UI has no stable public DOM contract. Unknown rows are skipped.
const chatRoot = '/space/998603/channel/_Dqixdn/chats';

function visible(element) {
  const box = element.getBoundingClientRect();
  return box.width > 0 && box.height > 0 && getComputedStyle(element).visibility !== 'hidden';
}

function hash(value) {
  let number = 2166136261;
  for (const char of value) number = Math.imul(number ^ char.charCodeAt(0), 16777619);
  return (number >>> 0).toString(36);
}

async function imageType(blob) {
  const bytes = new Uint8Array(await blob.slice(0, 12).arrayBuffer());
  if (bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return 'image/jpeg';
  if ([137, 80, 78, 71, 13, 10, 26, 10].every((value, index) => bytes[index] === value)) return 'image/png';
  if (String.fromCharCode(...bytes.slice(0, 4)) === 'RIFF' &&
      String.fromCharCode(...bytes.slice(8, 12)) === 'WEBP') return 'image/webp';
  if (String.fromCharCode(...bytes.slice(0, 3)) === 'GIF') return 'image/gif';
  return null;
}

async function photoDataUrl(blob) {
  const mime = await imageType(blob);
  if (!mime || blob.size > 10 * 1024 * 1024) throw new Error('사진 형식 또는 크기를 확인할 수 없습니다.');
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(new Blob([blob], {type: mime}));
  });
}

async function bundlePhotos(item) {
  const button = item.querySelector('.item_expiry .btn_save');
  const anchor = item.querySelector('.item_expiry a[download]');
  const count = item.querySelectorAll('.box_package img.thumb_g').length;
  if (!button || !anchor || !count) throw new Error('묶음 사진을 확인할 수 없습니다.');
  const pending = [];
  const intercept = event => {
    event.preventDefault();
    event.stopPropagation();
    const url = anchor.href;
    pending.push(fetch(url).then(response => {
      if (!response.ok) throw new Error('카카오 사진 가져오기 실패');
      return response.blob();
    }).then(photoDataUrl));
  };
  anchor.addEventListener('click', intercept, true);
  try {
    button.click();
    for (let attempt = 0; attempt < 100 && pending.length < count; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    if (pending.length !== count) throw new Error(`묶음 사진 ${count}장 중 ${pending.length}장만 확인했습니다.`);
    return await Promise.all(pending);
  } finally {
    anchor.removeEventListener('click', intercept, true);
  }
}

async function unreadRows() {
  for (let attempt = 0; attempt < 40 && !document.querySelector('.ReactVirtualized__List.list_board'); attempt++) {
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  const list = document.querySelector('.ReactVirtualized__List.list_board');
  if (!list) throw new Error('카카오채널 채팅 목록을 찾지 못했습니다. 화면 구조 확인이 필요합니다.');
  const originalTop = list.scrollTop;
  const rows = new Map();
  const step = Math.max(250, Math.floor(list.clientHeight * 0.75));
  try {
    for (let top = 0; top <= list.scrollHeight; top += step) {
      list.scrollTop = Math.min(top, list.scrollHeight - list.clientHeight);
      await new Promise(resolve => setTimeout(resolve, 60));
      for (const row of list.querySelectorAll('li')) {
        const badge = row.querySelector('.num_round');
        if (!badge || !/^\d+$/.test(badge.textContent.trim())) continue;
        const room_name = row.querySelector('.txt_name')?.textContent.trim();
        const preview = row.querySelector('.txt_info')?.textContent.trim() || '';
        const chatId = row.querySelector('label[for^="chat-select-"]')?.htmlFor.split('chat-select-')[1];
        const time = row.querySelector('.txt_date')?.textContent.trim() || '';
        if (!room_name || !/^\d+$/.test(chatId || '')) continue;
        const chat_url = `${location.origin}${chatRoot}/${chatId}`;
        const source_key = `kakao:${chatId}:${hash(preview + '|' + time + '|' + badge.textContent.trim())}`;
        rows.set(source_key, {source_key, chat_url, room_name, preview,
          unread_count: Number(badge.textContent.trim())});
      }
      if (list.scrollTop >= list.scrollHeight - list.clientHeight) break;
    }
  } finally {
    list.scrollTop = originalTop;
  }
  return [...rows.values()];
}

async function captureChat(chatUrl, preview, unreadCount) {
  if (location.href !== chatUrl) throw new Error('다른 채팅방이 열렸습니다.');

  if (!Number.isInteger(unreadCount) || unreadCount < 1 || unreadCount > 100) {
    throw new Error('읽지 않은 메시지 수를 확인하지 못했습니다.');
  }
  for (let attempt = 0; attempt < 40 && !document.querySelector('.item_chat'); attempt++) {
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  const groups = [];
  for (const item of document.querySelectorAll('.item_chat')) {
    if (item.classList.contains('item_start') || !groups.length) {
      groups.push({outgoing: item.classList.contains('item_me'), items: []});
    }
    groups[groups.length - 1].items.push(item);
  }
  const incoming = groups.filter(group => !group.outgoing).slice(-unreadCount);
  if (!incoming.length) throw new Error('최근 수신 메시지를 찾지 못했습니다.');
  const selected = incoming.flatMap(group => group.items);
  const message_text = selected.flatMap(item => [...item.querySelectorAll('.txt_chat')]
    .map(node => node.innerText.trim())).filter(Boolean).join('\n').slice(0, 5000) ||
    (/^사진\s*\d+장$/.test(preview || '') ? '' : preview || '');
  const imageLinks = selected.flatMap(item => [...item.querySelectorAll('a.btn_save[href*="/chatlogs/"]')]);
  const bundles = selected.filter(item => item.querySelector('.box_package'));
  const expectedCount = imageLinks.length + bundles.reduce((sum, item) => sum + item.querySelectorAll('.box_package img.thumb_g').length, 0);
  if (expectedCount > 10) throw new Error('사진이 10장을 넘습니다. 직접 확인해 주세요.');
  const dataUrls = [];
  for (const link of imageLinks) {
    try {
      const response = await fetch(link.href, {credentials: 'include'});
      if (!response.ok) throw new Error('사진 가져오기 실패');
      dataUrls.push(await photoDataUrl(await response.blob()));
    } catch (_) { /* A failed image is reported as a capture failure below. */ }
  }
  for (const item of bundles) dataUrls.push(...await bundlePhotos(item));
  if (dataUrls.length !== expectedCount) {
    throw new Error(`사진 ${expectedCount}장 중 ${dataUrls.length}장만 가져왔습니다. 직접 확인해 주세요.`);
  }
  return {message_text, images: dataUrls, chat_url: location.href};
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => message.action === 'scan' ? unreadRows() : captureChat(message.chat_url, message.preview, message.unread_count))()
    .then(sendResponse, error => sendResponse({__error: error.message}));
  return true;
});
