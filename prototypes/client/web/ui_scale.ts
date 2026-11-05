export const UI_SCALE_KEY = "aw2-client-ui-scale";
export const UI_SCALE_MIN = 50;
export const UI_SCALE_MAX = 200;
export const UI_SCALE_STEP = 10;
export const UI_SCALE_DEFAULT = 100;

function storageOrNull(storage?: Storage): Storage | null {
  try {
    return storage ?? window.localStorage;
  } catch {
    return null;
  }
}

export function normalizeUiScale(value: number): number {
  if (!Number.isFinite(value)) return UI_SCALE_DEFAULT;
  const clamped = Math.min(UI_SCALE_MAX, Math.max(UI_SCALE_MIN, value));
  return (
    Math.round((clamped - UI_SCALE_MIN) / UI_SCALE_STEP) * UI_SCALE_STEP +
    UI_SCALE_MIN
  );
}

export function readUiScale(storage?: Storage): number {
  try {
    const value = storageOrNull(storage)?.getItem(UI_SCALE_KEY);
    if (value === null || value === undefined || value.trim() === "")
      return UI_SCALE_DEFAULT;
    const parsed = Number(value);
    return Number.isFinite(parsed)
      ? normalizeUiScale(parsed)
      : UI_SCALE_DEFAULT;
  } catch {
    return UI_SCALE_DEFAULT;
  }
}

export function saveUiScale(value: number, storage?: Storage): void {
  try {
    storageOrNull(storage)?.setItem(
      UI_SCALE_KEY,
      String(normalizeUiScale(value)),
    );
  } catch {
    // Keep the in-memory preference when browser storage is unavailable.
  }
}

export function applyUiScale(root: HTMLElement, value: number): void {
  root.style.setProperty("zoom", `${normalizeUiScale(value) / 100}`);
}

export function initializeUiScale(): void {
  applyUiScale(document.documentElement, readUiScale());
}
