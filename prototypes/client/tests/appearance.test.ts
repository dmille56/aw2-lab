import { afterEach, describe, expect, it } from "vitest";
import {
  DEFAULT_THEME,
  LEGACY_APPEARANCE_KEY,
  readThemePreference,
  saveThemePreference,
  THEMES,
  THEME_PREFERENCE_KEY,
  initializeTheme,
} from "../web/appearance";

afterEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("data-appearance");
  document.documentElement.removeAttribute("style");
});

describe("theme preferences", () => {
  it("defaults to the registered theme and restores its mode", () => {
    expect(readThemePreference()).toEqual(DEFAULT_THEME);
    saveThemePreference({ theme: "classic", appearance: "light" });
    expect(readThemePreference()).toEqual({
      theme: "classic",
      appearance: "light",
    });
    saveThemePreference({ theme: "gruvbox", appearance: "dark" });
    expect(readThemePreference()).toEqual({
      theme: "gruvbox",
      appearance: "dark",
    });
    localStorage.setItem(THEME_PREFERENCE_KEY, "invalid");
    expect(readThemePreference()).toEqual(DEFAULT_THEME);
  });

  it("migrates an earlier appearance-only setting", () => {
    localStorage.setItem(LEGACY_APPEARANCE_KEY, "dark");
    expect(readThemePreference()).toEqual({
      theme: "classic",
      appearance: "dark",
    });
  });

  it("requires every registered theme to define both color variants", () => {
    for (const definition of Object.values(THEMES)) {
      expect(definition.variants.light["--page"]).toBeTruthy();
      expect(definition.variants.dark["--page"]).toBeTruthy();
    }
  });

  it("applies the selected palette before rendering", () => {
    saveThemePreference({ theme: "classic", appearance: "dark" });
    initializeTheme();
    expect(localStorage.getItem(THEME_PREFERENCE_KEY)).toContain('"dark"');
    expect(document.documentElement.dataset.theme).toBe("classic");
    expect(document.documentElement.dataset.appearance).toBe("dark");
    expect(document.documentElement.style.colorScheme).toBe("dark");
    expect(document.documentElement.style.getPropertyValue("--page")).toBe(
      THEMES.classic.variants.dark["--page"],
    );
  });
});
