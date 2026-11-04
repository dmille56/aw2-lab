import { API_BASE } from "./transport.js";

const button = document.querySelector("#check");
const result = document.querySelector("#result");

async function checkConnection() {
  button.disabled = true;
  result.textContent = "Connecting…";
  let connected = false;
  try {
    const response = await fetch(`${API_BASE}/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const health = await response.json();
    if (health.status !== "ok" || typeof health.emulator !== "string") {
      throw new Error("Unrecognized health response");
    }
    result.textContent = `Connected\n${JSON.stringify(health, null, 2)}`;
    connected = true;
  } catch (error) {
    result.textContent =
      `Cannot reach the AW2 Lab server at ${API_BASE || location.origin}.\n` +
      `Start the local server, then choose Check connection.\nDetails: ${error.message}`;
  } finally {
    button.disabled = false;
  }
  if (window.__TAURI__) {
    await window.__TAURI__.core.invoke("report_connection", {
      connected,
      message: result.textContent,
    });
  }
}

button.addEventListener("click", checkConnection);
checkConnection();
