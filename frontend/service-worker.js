const CACHE_NAME = "taskflow-shell-v1";
const SHELL = ["/dashboard.html", "/style.css", "/script.js", "/dashboard.js", "/login.html"];

self.addEventListener("install", event => {
    event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL)));
});

self.addEventListener("activate", event => {
    event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", event => {
    if (event.request.method !== "GET" || event.request.url.includes("/api/")) return;
    event.respondWith(caches.match(event.request).then(cached => cached || fetch(event.request)));
});

self.addEventListener("push", event => {
    const data = event.data ? event.data.json() : { title: "TaskFlow", body: "You have a new workspace update." };
    event.waitUntil(self.registration.showNotification(data.title, { body: data.body, icon: "/" }));
});
