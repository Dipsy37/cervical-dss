// Progressive Web App support: registers the service worker, shows an offline banner,
// and offers an "Install app" button where the browser allows it.
(function () {
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js").catch(() => { /* app still works without it */ });
    });
  }

  // Offline banner: tells the CHW why buttons that need the server will not work right now.
  function updateBanner() {
    let bar = document.getElementById("offlineBanner");
    if (navigator.onLine) { if (bar) bar.remove(); return; }
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "offlineBanner";
      bar.className = "offline-banner";
      bar.setAttribute("role", "status");
      bar.textContent = "You are offline. Assessments need a connection and will not be saved until you reconnect.";
      document.body.prepend(bar);
    }
  }
  window.addEventListener("online", updateBanner);
  window.addEventListener("offline", updateBanner);
  document.addEventListener("DOMContentLoaded", updateBanner);

  // Install button (Android Chrome / Edge). The page decides where the button goes: id="installApp".
  let deferred = null;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferred = e;
    const btn = document.getElementById("installApp");
    if (btn) btn.classList.remove("hidden");
  });
  document.addEventListener("click", async (e) => {
    if (!e.target.closest || !e.target.closest("#installApp") || !deferred) return;
    deferred.prompt();
    await deferred.userChoice;
    deferred = null;
    document.getElementById("installApp").classList.add("hidden");
  });
  window.addEventListener("appinstalled", () => {
    const btn = document.getElementById("installApp");
    if (btn) btn.classList.add("hidden");
  });
})();
