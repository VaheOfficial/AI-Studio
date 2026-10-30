self.addEventListener('push', event => {
  let data = {};
  try { data = event.data?.json() || {}; } catch { return; }
  event.waitUntil(self.registration.showNotification(String(data.title || 'Agent update'), {
    body: String(data.body || 'Open Agents to inspect the update.'), data: { session_id: data.session_id }, tag: 'agent-' + String(data.session_id || ''),
  }));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(clients.matchAll({ type:'window', includeUncontrolled:true }).then(windows => {
    const open = windows.find(window => new URL(window.url).origin === self.location.origin);
    return open ? open.focus() : clients.openWindow('/');
  }));
});
