import { describe, expect, it } from "vitest";
import { terrainSpriteRegion, validateSpriteManifest } from "../web/sprites";
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

it("allows complete 48x48 native portraits while retaining map sprite limits", () => {
  const wide = {
    ...pack,
    width: 64,
    height: 64,
    portraits: { 1: { x: 0, y: 0, width: 48, height: 48 } },
  };
  expect(validateSpriteManifest(wide)).toEqual(wide);
  expect(() =>
    validateSpriteManifest({
      ...wide,
      units: { "1:1": { x: 0, y: 0, width: 48, height: 48 } },
    }),
  ).toThrow();
});

it("selects native coastal variants and keeps safe legacy/symbolic fallbacks", () => {
  const region = { x: 0, y: 0, width: 16, height: 32 };
  const variants = {
    "13:16": region,
    "13:46": { ...region, x: 16 },
    "13:47": { ...region, x: 32 },
    "13:50": { ...region, x: 48 },
    "7:42": region,
  };
  const coastal = {
    ...pack,
    width: 64,
    image: "synthetic",
    terrain: { ...pack.terrain, "7:0": region, "13:0": region },
    terrain_variants: variants,
  };
  expect(validateSpriteManifest(coastal)).toEqual(coastal);
  for (const id of [16, 46, 47, 50])
    expect(
      terrainSpriteRegion(coastal, {
        terrain_class: 13,
        graphical_tile_id: id,
        owner_slot: 0,
      }),
    ).toBe(variants[`13:${id}` as keyof typeof variants]);
  const legacy = { ...pack, image: "synthetic", terrain: coastal.terrain };
  expect(
    terrainSpriteRegion(legacy, {
      terrain_class: 13,
      graphical_tile_id: 16,
      owner_slot: 0,
    }),
  ).toBeUndefined();
  expect(
    terrainSpriteRegion(legacy, {
      terrain_class: 7,
      graphical_tile_id: 42,
      owner_slot: 0,
    }),
  ).toBe(region);
  expect(
    terrainSpriteRegion(coastal, {
      terrain_class: 13,
      graphical_tile_id: 999,
      owner_slot: 0,
    }),
  ).toBeUndefined();
});
it.each(["13:1024", "13:-1", "13:0016", "6:16"])(
  "rejects invalid coastal variant key %s",
  (key) => {
    expect(() =>
      validateSpriteManifest({
        ...pack,
        terrain_variants: { [key]: { x: 0, y: 0, width: 16, height: 32 } },
      }),
    ).toThrow();
  },
);
