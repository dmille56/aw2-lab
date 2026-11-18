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

it("selects native terrain variants and keeps safe legacy/symbolic fallbacks", () => {
  const region = { x: 0, y: 0, width: 16, height: 32 };
  const variants = {
    "1:1": region,
    "1:67": { ...region, x: 16 },
    "3:2": region,
    "3:34": { ...region, x: 64 },
    "3:35": { ...region, x: 80 },
    "4:134": { ...region, x: 48 },
    "4:135": { ...region, x: 32 },
    "5:64": { ...region, x: 16 },
    "13:16": region,
    "13:46": { ...region, x: 16 },
    "13:47": { ...region, x: 32 },
    "13:50": { ...region, x: 48 },
    "7:42": region,
  };
  const coastal = {
    ...pack,
    width: 96,
    image: "synthetic",
    terrain: {
      ...pack.terrain,
      "1:0": region,
      "3:0": region,
      "4:0": region,
      "5:0": region,
      "6:3": region,
      "7:0": region,
      "13:0": region,
    },
    terrain_variants: variants,
  };
  expect(validateSpriteManifest(coastal)).toEqual(coastal);
  for (const id of [2, 34, 35])
    expect(
      terrainSpriteRegion(coastal, {
        terrain_class: 3,
        graphical_tile_id: id,
        owner_slot: 0,
      }),
    ).toBe(variants[`3:${id}` as keyof typeof variants]);
  expect(
    terrainSpriteRegion(coastal, {
      terrain_class: 3,
      graphical_tile_id: 7,
      owner_slot: 0,
    }),
  ).toBe(region);
  for (const id of [134, 135])
    expect(
      terrainSpriteRegion(coastal, {
        terrain_class: 4,
        graphical_tile_id: id,
        owner_slot: 0,
      }),
    ).toBe(variants[`4:${id}` as keyof typeof variants]);
  expect(
    terrainSpriteRegion(coastal, {
      terrain_class: 5,
      graphical_tile_id: 64,
      owner_slot: 0,
    }),
  ).toBe(variants["5:64"]);
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
      terrain_class: 3,
      graphical_tile_id: 34,
      owner_slot: 0,
    }),
  ).toBe(legacy.terrain["3:0"]);
  expect(
    terrainSpriteRegion(coastal, {
      terrain_class: 1,
      graphical_tile_id: 67,
      owner_slot: 0,
    }),
  ).toBe(variants["1:67"]);
  // Plains cells with an unlisted graphical ID still fall back to the class sprite.
  expect(
    terrainSpriteRegion(coastal, {
      terrain_class: 1,
      graphical_tile_id: 262,
      owner_slot: 0,
    }),
  ).toBe(region);
  // Property artwork follows the owning army, never a per-cell graphical ID.
  expect(
    terrainSpriteRegion(coastal, {
      terrain_class: 6,
      graphical_tile_id: 455,
      owner_slot: 3,
    }),
  ).toBe(coastal.terrain["6:3"]);
  expect(
    terrainSpriteRegion(legacy, {
      terrain_class: 1,
      graphical_tile_id: 67,
      owner_slot: 0,
    }),
  ).toBe(legacy.terrain["1:0"]);
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
    terrainSpriteRegion(legacy, {
      terrain_class: 5,
      graphical_tile_id: 64,
      owner_slot: 0,
    }),
  ).toBe(legacy.terrain["5:0"]);
  expect(
    terrainSpriteRegion(legacy, {
      terrain_class: 4,
      graphical_tile_id: 134,
      owner_slot: 0,
    }),
  ).toBe(legacy.terrain["4:0"]);
  expect(
    terrainSpriteRegion(coastal, {
      terrain_class: 13,
      graphical_tile_id: 999,
      owner_slot: 0,
    }),
  ).toBeUndefined();
});
it.each([
  "13:1024",
  "13:-1",
  "13:0016",
  "6:16",
  "8:16",
  "11:16",
  "20:1",
  "5:1024",
  "4:1024",
  "3:1024",
  "3:0032",
  "1:1024",
])("rejects invalid terrain variant key %s", (key) => {
  expect(() =>
    validateSpriteManifest({
      ...pack,
      terrain_variants: { [key]: { x: 0, y: 0, width: 16, height: 32 } },
    }),
  ).toThrow();
});
