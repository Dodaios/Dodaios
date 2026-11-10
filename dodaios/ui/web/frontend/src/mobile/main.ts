/**
 * Entry of the phone companion (m/index.html → /m/).
 *
 * Reads the pairing code from the URL fragment (and removes it from the
 * address so it is never bookmarked or shared), registers the service worker
 * when the context is secure, and starts the app.
 */
import "./mobile.css";
import { MobileApi, pairingCodeFromHash, safeStorage } from "./api";
import { PhoneApp } from "./app";
import { pickLanguage, setLanguage } from "./strings";

async function registerWorker(): Promise<ServiceWorkerRegistration | null> {
  if (!("serviceWorker" in navigator) || !window.isSecureContext) return null;
  try {
    return await navigator.serviceWorker.register("/m/sw.js", { scope: "/m/" });
  } catch {
    return null;
  }
}

async function boot(): Promise<void> {
  setLanguage(pickLanguage(navigator.languages?.length ? navigator.languages : [navigator.language]));
  const code = pairingCodeFromHash(window.location.hash);
  if (code) history.replaceState(null, "", window.location.pathname);
  const root = document.getElementById("app");
  if (!root) return;
  const registration = await registerWorker();
  const app = new PhoneApp({ root, api: new MobileApi(safeStorage()), pairingCode: code, registration });
  await app.start();
}

void boot();
