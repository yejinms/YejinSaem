const BRIDGE = 'yejinsaem-channel-intake-v1';
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.action === 'ping') sendResponse({bridge: BRIDGE, origin: location.origin});
});
window.addEventListener('message', async event => {
  if (event.source !== window || event.origin !== location.origin ||
      event.data?.bridge !== BRIDGE || event.data?.direction !== 'to-extension') return;
  const {requestId, action, payload} = event.data;
  if (!['scan', 'open'].includes(action) || typeof requestId !== 'string') return;
  try {
    const response = await chrome.runtime.sendMessage({action, payload});
    window.postMessage({bridge: BRIDGE, direction: 'to-page', requestId,
      ...(response?.error ? {error: response.error} : {result: response?.result})}, location.origin);
  } catch (error) {
    window.postMessage({bridge: BRIDGE, direction: 'to-page', requestId, error: error.message}, location.origin);
  }
});
