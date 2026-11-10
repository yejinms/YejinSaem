const KAKAO_LIST_URL = 'https://business.kakao.com/space/998603/channel/_Dqixdn/chats';

async function kakaoTabs() {
  const tabs = await chrome.tabs.query({url: 'https://business.kakao.com/space/*/channel/*/chats*'});
  if (tabs.length) return tabs.sort((a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0));
  const tab = await chrome.tabs.create({url: KAKAO_LIST_URL, active: true});
  await waitForLoaded(tab.id, true);
  return [tab];
}

function waitForLoaded(tabId, acceptAlreadyLoaded = false) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      reject(new Error('카카오채널 채팅 로딩 시간 초과'));
    }, 15000);
    function listener(updatedId, info) {
      if (updatedId === tabId && info.status === 'complete') {
        clearTimeout(timeout);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    }
    chrome.tabs.onUpdated.addListener(listener);
    if (acceptAlreadyLoaded) chrome.tabs.get(tabId).then(tab => {
      if (tab.status === 'complete') {
        clearTimeout(timeout);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    }).catch(reject);
  });
}

async function captureChat(payload) {
  const chatUrl = payload?.chat_url;
  if (!/^https:\/\/business\.kakao\.com\/space\/998603\/channel\/_Dqixdn\/chats\/\d+$/.test(chatUrl || '')) {
    throw new Error('카카오채널 채팅 주소가 올바르지 않습니다.');
  }
  const tabs = await kakaoTabs();
  const tab = tabs.find(item => item.url === KAKAO_LIST_URL) || tabs[0];
  if (tab.url !== chatUrl) {
    const loaded = waitForLoaded(tab.id);
    await chrome.tabs.update(tab.id, {url: chatUrl, active: true});
    await loaded;
  } else {
    const loaded = waitForLoaded(tab.id);
    await chrome.tabs.reload(tab.id);
    await loaded;
  }
  return chrome.tabs.sendMessage(tab.id, {action: 'capture', ...payload});
}

async function scanUnread() {
  const tabs = await kakaoTabs();
  let tab = tabs.find(item => item.url === KAKAO_LIST_URL);
  if (!tab) {
    tab = await chrome.tabs.create({url: KAKAO_LIST_URL, active: true});
    await waitForLoaded(tab.id, true);
  }
  try {
    const result = await chrome.tabs.sendMessage(tab.id, {action: 'scan'});
    if (result?.__error) throw new Error(result.__error);
    return result;
  } catch (_) {
    const loaded = waitForLoaded(tab.id);
    await chrome.tabs.reload(tab.id);
    await loaded;
    const result = await chrome.tabs.sendMessage(tab.id, {action: 'scan'});
    if (result?.__error) throw new Error(result.__error);
    return result;
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!sender.url?.startsWith('https://yejinsaem-production.up.railway.app/') &&
      !sender.url?.startsWith('http://localhost:8000/') &&
      !sender.url?.startsWith('http://127.0.0.1:8000/')) return;
  (async () => {
    if (message.action === 'open') {
      const result = await captureChat(message.payload);
      if (result?.__error) throw new Error(result.__error);
      return result;
    }
    return scanUnread();
  })().then(result => sendResponse({result}), error => sendResponse({error: error.message}));
  return true;
});
