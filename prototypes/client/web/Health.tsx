import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE } from "./transport";
import { message } from "./session";

export function Health() {
  const [result, setResult] = useState("Not checked.");
  const [pending, setPending] = useState(false);
  const current = useRef<AbortController | null>(null);
  const check = useCallback(async () => {
    current.current?.abort();
    const controller = new AbortController();
    current.current = controller;
    setPending(true);
    setResult("Connecting…");
    let connected = false,
      text: string;
    try {
      const response = await fetch(`${API_BASE}/health`, {
        cache: "no-store",
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(5000)]),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const health: unknown = await response.json();
      if (
        typeof health !== "object" ||
        health === null ||
        !("status" in health) ||
        health.status !== "ok" ||
        !("emulator" in health) ||
        typeof health.emulator !== "string"
      )
        throw new Error("Unrecognized health response");
      text = `Connected\n${JSON.stringify(health, null, 2)}`;
      connected = true;
    } catch (error) {
      text = `Cannot reach the AW2 Lab server at ${API_BASE || location.origin}.\nStart the local server, then choose Check connection.\nDetails: ${message(error)}`;
    }
    if (controller.signal.aborted) return;
    setPending(false);
    setResult(text);
    if (window.__TAURI__)
      await window.__TAURI__.core.invoke("report_connection", {
        connected,
        message: text,
      });
  }, []);
  useEffect(() => {
    void check();
    return () => current.current?.abort();
  }, [check]);
  return (
    <section className="card" aria-label="Server connection">
      <div className="toolbar">
        <h2>Server connection</h2>
        <button type="button" id="check" disabled={pending} onClick={check}>
          Check connection
        </button>
      </div>
      <pre id="result" role="status" aria-live="polite">
        {result}
      </pre>
    </section>
  );
}
