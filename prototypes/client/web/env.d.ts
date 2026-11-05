/// <reference types="vite/client" />
interface Window {
  __TAURI__?: {
    core: {
      invoke(command: string, args: Record<string, unknown>): Promise<unknown>;
    };
  };
}
