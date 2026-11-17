import { describe, expect, it } from "vitest";
import { validateSpriteManifest } from "../web/sprites";
const pack = {
  kind: "aw2-client-sprites",
  version: 1,
  atlas: `atlas-${"a".repeat(64)}.png`,
  width: 16,
  height: 32,
  units: { "1:1": { x: 0, y: 0, width: 16, height: 16 } },
  terrain: { "6:1": { x: 0, y: 0, width: 16, height: 32 } },
};
describe("local sprite manifest", () => {
  it("accepts bounded versioned regions", () => {
    expect(validateSpriteManifest(pack)).toEqual(pack);
  });
  it.each([
    null,
    { ...pack, version: 2 },
    { ...pack, atlas: "../rom.gba" },
    { ...pack, width: 0 },
    { ...pack, units: { "1:1": { x: 1, y: 0, width: 16, height: 16 } } },
    { ...pack, terrain: [] },
  ])("rejects absent or malformed packs", (value) => {
    expect(() => validateSpriteManifest(value)).toThrow();
  });
});

it("accepts optional CO portraits and rejects invalid IDs or atlas bounds", () => {
  const portraits = { "1": { x: 0, y: 0, width: 16, height: 24 } };
  expect(validateSpriteManifest({ ...pack, portraits }).portraits).toEqual(
    portraits,
  );
  expect(() =>
    validateSpriteManifest({ ...pack, portraits: { "19": portraits["1"] } }),
  ).toThrow();
  expect(() =>
    validateSpriteManifest({
      ...pack,
      portraits: { "1": { ...portraits["1"], x: 1 } },
    }),
  ).toThrow();
});
