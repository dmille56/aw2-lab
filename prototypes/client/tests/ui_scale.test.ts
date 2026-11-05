import { afterEach, describe, expect, it } from "vitest";
import {
  applyUiScale,
  initializeUiScale,
  normalizeUiScale,
  readUiScale,
  saveUiScale,
  UI_SCALE_DEFAULT,
  UI_SCALE_KEY,
  UI_SCALE_MAX,
  UI_SCALE_MIN,
} from "../web/ui_scale";

afterEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("style");
});

describe("interface scale", () => {
  it("defaults to 100 percent and restores a saved value", () => {
    expect(readUiScale()).toBe(UI_SCALE_DEFAULT);
    saveUiScale(130);
    expect(readUiScale()).toBe(130);
  });

  it("clamps and snaps values to supported steps", () => {
    expect(UI_SCALE_MIN).toBe(50);
    expect(normalizeUiScale(30)).toBe(UI_SCALE_MIN);
    expect(normalizeUiScale(201)).toBe(UI_SCALE_MAX);
    expect(normalizeUiScale(124)).toBe(120);
    expect(normalizeUiScale(Number.NaN)).toBe(UI_SCALE_DEFAULT);
    localStorage.setItem(UI_SCALE_KEY, "not-a-number");
    expect(readUiScale()).toBe(UI_SCALE_DEFAULT);
  });

  it("applies the saved scale before rendering", () => {
    saveUiScale(200);
    initializeUiScale();
    expect(document.documentElement.style.getPropertyValue("zoom")).toBe("2");
  });

  it("normalizes values before saving and applying them", () => {
    saveUiScale(201);
    applyUiScale(document.documentElement, readUiScale());
    expect(readUiScale()).toBe(UI_SCALE_MAX);
    expect(document.documentElement.style.getPropertyValue("zoom")).toBe("2");
  });
});
