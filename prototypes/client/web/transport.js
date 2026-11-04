// Browser assets share the API origin. The existing native shell supports the
// explicitly configured local server; credentials never affect this destination.
export const API_BASE = window.__TAURI__ ? "http://127.0.0.1:43127" : "";
