const button = document.querySelector("#check");
const result = document.querySelector("#result");

async function checkConnection() {
  button.disabled = true;
  result.textContent = "Connecting…";
  // The browser is served with the API; native assets have their own origin.
  const base = location.port === "43127" ? "" : "http://127.0.0.1:43127";
  let connected = false;
  try {
    const response = await fetch(`${base}/health`, {
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
    result.textContent = `Connection failed: ${error.message}`;
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
