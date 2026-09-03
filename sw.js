// Minimal service worker — sadece PWA "yüklenebilir" (installable) şartını
// karşılamak için var. Şimdilik önbellekleme yapmıyor, sadece kayıtlı olması yeterli.
self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  // Şimdilik ağdan direkt geçiriyor, ileride offline önbellekleme eklenebilir.
});
