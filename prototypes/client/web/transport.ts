// Browser and Vite development requests share the API origin/proxy. Packaged
// native assets use the explicitly supported loopback server.
export const apiBase = (native: boolean, production: boolean) =>
  native && production ? "http://127.0.0.1:43127" : "";
export const API_BASE = apiBase(
  Boolean(window.__TAURI__),
  import.meta.env.PROD,
);

let nativeApiBase: Promise<string> | null = null;
export function getApiBase(): Promise<string> {
  if (!window.__TAURI__ || !import.meta.env.PROD)
    return Promise.resolve(API_BASE);
  nativeApiBase ??= window.__TAURI__.core
    .invoke("client_api_base", {})
    .then((value) =>
      typeof value === "string" && /^http:\/\/127\.0\.0\.1:\d+$/.test(value)
        ? value
        : API_BASE,
    )
    .catch(() => API_BASE);
  return nativeApiBase;
}
