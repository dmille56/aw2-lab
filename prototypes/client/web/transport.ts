// Browser and Vite development requests share the API origin/proxy. Packaged
// native assets use the explicitly supported loopback server.
export const apiBase = (native: boolean, production: boolean) =>
  native && production ? "http://127.0.0.1:43127" : "";
export const API_BASE = apiBase(
  Boolean(window.__TAURI__),
  import.meta.env.PROD,
);
