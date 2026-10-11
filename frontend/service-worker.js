const CACHE_NAME = "taskflow-shell-v6";
const SHELL = ["/dashboard.html", "/style.css", "/script.js", "/dashboard.js", "/login.html"];

self.addEventListener("install", event => {
    event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", event => {
    event.waitUntil(
        caches.keys()
            .then(keys => Promise.all(keys.filter(key => key.startsWith("taskflow-shell-") && key !== CACHE_NAME).map(key => caches.delete(key))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", event => {
    if (event.request.method !== "GET" || event.request.url.includes("/api/")) return;
    event.respondWith(
        fetch(event.request)
            .then(response => {
                if (response.ok) {
                    const responseCopy = response.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(event.request, responseCopy));
                }
                return response;
            })
            .catch(() => caches.match(event.request))
    );
});

self.addEventListener("push", event => {
    const data = event.data ? event.data.json() : { title: "TaskFlow", body: "You have a new workspace update." };
    event.waitUntil(self.registration.showNotification(data.title, { body: data.body, icon: "/" }));
});
