import "./styles.css";
import { boot } from "./app";

async function registerOfflineSupport(): Promise<void> {
  if (!("serviceWorker" in navigator)) return;
  try {
    const registration = await navigator.serviceWorker.register("./sw.js", { scope: "./" });
    await navigator.serviceWorker.ready;
    if (navigator.serviceWorker.controller) {
      registration.active?.postMessage({ type: "CHECK_PRECACHE" });
    }
  } catch { /* Offline caching is best-effort and intentionally has no page-level status label. */ }
}

void boot();
if (!document.getElementById("answer-recorder-config") && !document.getElementById("answer-recorder-state")) void registerOfflineSupport();
