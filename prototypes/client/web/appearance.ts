export const THEME_PREFERENCE_KEY = "aw2-client-theme-preference";
export const LEGACY_APPEARANCE_KEY = "aw2-client-appearance";

export type Appearance = "system" | "light" | "dark";
export type ThemeVariant = Exclude<Appearance, "system">;
export type ThemePalette = Record<`--${string}`, string>;
export type ThemeDefinition = {
  label: string;
  variants: Record<ThemeVariant, ThemePalette>;
};

// Every theme must provide both variants. Add palettes here; the theme picker
// appears automatically once a second theme is registered.
export const THEMES = {
  classic: {
    label: "Classic",
    variants: {
      light: {
        "--page": "#f4f6f8",
        "--text": "#18232e",
        "--muted": "#4c5b68",
        "--card": "#fff",
        "--border": "#c4cdd5",
        "--control": "#e6edf2",
        "--control-hover": "#d5e1e9",
        "--control-border": "#8293a1",
        "--control-text": "#18232e",
        "--input": "#fff",
        "--accent": "#00666f",
        "--focus-on-board": "#142536",
        "--player-card": "#f4f6f8",
        "--legend": "#e6edf2",
        "--error": "#fce8e8",
        "--board": "#14202a",
      },
      dark: {
        "--page": "#101923",
        "--text": "#e6edf6",
        "--muted": "#afc0cf",
        "--card": "#192633",
        "--border": "#334657",
        "--control": "#243749",
        "--control-hover": "#35516b",
        "--control-border": "#526779",
        "--control-text": "#fff",
        "--input": "#101923",
        "--accent": "#86cbd1",
        "--focus-on-board": "#fff",
        "--player-card": "#101923",
        "--legend": "#253a4b",
        "--error": "#582d32",
        "--board": "#14202a",
      },
    },
  },
  gruvbox: {
    label: "Gruvbox",
    variants: {
      light: {
        "--page": "#fbf1c7",
        "--text": "#3c3836",
        "--muted": "#665c54",
        "--card": "#f2e5bc",
        "--border": "#d5c4a1",
        "--control": "#ebdbb2",
        "--control-hover": "#d5c4a1",
        "--control-border": "#a89984",
        "--control-text": "#3c3836",
        "--input": "#fbf1c7",
        "--accent": "#076678",
        "--focus-on-board": "#282828",
        "--player-card": "#f9f5d7",
        "--legend": "#ebdbb2",
        "--error": "#f9e0d9",
        "--board": "#d5c4a1",
      },
      dark: {
        "--page": "#282828",
        "--text": "#ebdbb2",
        "--muted": "#bdae93",
        "--card": "#3c3836",
        "--border": "#504945",
        "--control": "#504945",
        "--control-hover": "#665c54",
        "--control-border": "#928374",
        "--control-text": "#fbf1c7",
        "--input": "#282828",
        "--accent": "#83a598",
        "--focus-on-board": "#fbf1c7",
        "--player-card": "#282828",
        "--legend": "#3c3836",
        "--error": "#3c1f1e",
        "--board": "#504945",
      },
    },
  },
} as const satisfies Record<string, ThemeDefinition>;

export type ThemeId = keyof typeof THEMES;
export type ThemePreference = { theme: ThemeId; appearance: Appearance };

export const DEFAULT_THEME: ThemePreference = {
  theme: "classic",
  appearance: "system",
};

function isThemeId(value: unknown): value is ThemeId {
  return typeof value === "string" && value in THEMES;
}

function isAppearance(value: unknown): value is Appearance {
  return value === "system" || value === "light" || value === "dark";
}

function getStorage(storage?: Storage): Storage | null {
  try {
    return storage ?? window.localStorage;
  } catch {
    return null;
  }
}

export function readThemePreference(storage?: Storage): ThemePreference {
  const target = getStorage(storage);
  if (!target) return { ...DEFAULT_THEME };

  try {
    const saved = target.getItem(THEME_PREFERENCE_KEY);
    if (saved) {
      const parsed: unknown = JSON.parse(saved);
      if (
        typeof parsed === "object" &&
        parsed !== null &&
        "theme" in parsed &&
        isThemeId(parsed.theme) &&
        "appearance" in parsed &&
        isAppearance(parsed.appearance)
      )
        return { theme: parsed.theme, appearance: parsed.appearance };
    }

    const legacy = target.getItem(LEGACY_APPEARANCE_KEY);
    if (isAppearance(legacy))
      return { theme: DEFAULT_THEME.theme, appearance: legacy };
  } catch {
    return { ...DEFAULT_THEME };
  }
  return { ...DEFAULT_THEME };
}

export function saveThemePreference(
  preference: ThemePreference,
  storage?: Storage,
): void {
  try {
    getStorage(storage)?.setItem(
      THEME_PREFERENCE_KEY,
      JSON.stringify(preference),
    );
  } catch {
    // Keep the in-memory preference when browser storage is unavailable.
  }
}

export function applyTheme(
  root: HTMLElement,
  preference: ThemePreference,
  systemDark: boolean,
): void {
  const variant: ThemeVariant =
    preference.appearance === "system"
      ? systemDark
        ? "dark"
        : "light"
      : preference.appearance;
  const definition = THEMES[preference.theme];
  root.dataset.theme = preference.theme;
  root.dataset.appearance = preference.appearance;
  root.style.colorScheme = variant;
  for (const [property, value] of Object.entries(definition.variants[variant]))
    root.style.setProperty(property, value);
}

export function initializeTheme(): void {
  const preference = readThemePreference();
  const systemDark =
    window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  applyTheme(document.documentElement, preference, systemDark);
}
