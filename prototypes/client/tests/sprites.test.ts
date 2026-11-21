import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  terrainArtwork,
  useSpritePack,
  validateSpriteManifest,
  validateTerrainAnimation,
} from "../web/sprites";

const terrainSpriteRegion = (...args: Parameters<typeof terrainArtwork>) =>
  terrainArtwork(...args)?.region;

afterEach(() => vi.unstubAllGlobals());
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

describe("optional terrain animation", () => {
  const digest = "b".repeat(64);
  const region = { x: 0, y: 0, width: 16, height: 32 };
  const frames = [region, { ...region, x: 16 }];
  const animation = {
    atlas: `animation-${digest}.png`,
    atlas_sha256: digest,
    width: 32,
    height: 32,
    cycle_frames: 8,
    frames: {
      terrain: { "6:1": frames, "7:0": frames, "7:1": [region] },
      terrain_variants: { "7:42": frames },
    },
  };

  it("uses frames only for the selected static region", () => {
    const validated = validateTerrainAnimation(animation)!;
    const coastal = {
      ...pack,
      image: "static",
      terrain: { ...pack.terrain, "7:0": region },
      terrain_variants: { "7:42": region, "7:43": region },
      animation: { ...validated, image: "animation" },
    };
    const sea = { terrain_class: 7, owner_slot: 0, graphical_tile_id: 42 };
    expect(validated.frames.terrain?.["7:1"]).toBeUndefined();
    expect(terrainArtwork(coastal, sea)?.frames).toEqual(frames);
    expect(terrainArtwork(coastal, { ...sea, graphical_tile_id: 43 })).toEqual({
      region,
      frames: undefined,
    });
    expect(
      terrainArtwork(coastal, { ...sea, graphical_tile_id: 44 })?.frames,
    ).toEqual(frames);
    expect(
      terrainArtwork(coastal, { ...sea, terrain_class: 6, owner_slot: 1 })
        ?.frames,
    ).toEqual(frames);
    expect(
      terrainArtwork(coastal, { ...sea, terrain_class: 6, owner_slot: 2 }),
    ).toBeUndefined();
  });

  it.each([
    undefined,
    null,
    { ...animation, atlas: "../animation.png" },
    { ...animation, cycle_frames: 0 },
    { ...animation, width: 16 },
    { ...animation, frames: { units: { "6:1": frames } } },
    { ...animation, frames: { terrain_variants: { "7:1024": frames } } },
    {
      ...animation,
      frames: { terrain: { "6:1": [...frames, { ...region, height: 16 }] } },
    },
  ])(
    "ignores missing or invalid animation without rejecting the base pack",
    (value) => {
      const manifest = validateSpriteManifest({ ...pack, animation: value });
      expect(validateTerrainAnimation(manifest.animation)).toBeUndefined();
      expect(manifest.terrain).toEqual(pack.terrain);
    },
  );

  it.each([32, 16])(
    "uses the decoded animation atlas only when its width matches (%i)",
    async (decodedWidth) => {
      const fetchAtlas = vi.fn((url: string) =>
        Promise.resolve(
          url.endsWith("/manifest.json")
            ? Response.json({ ...pack, animation })
            : new Response(
                url.endsWith(animation.atlas) ? "animation" : "static",
              ),
        ),
      );
      const createObjectURL = vi
        .fn<() => string>()
        .mockReturnValueOnce("blob:static")
        .mockReturnValueOnce("blob:animation");
      const revokeObjectURL = vi.fn<(url: string) => void>();
      vi.stubGlobal("fetch", fetchAtlas);
      vi.stubGlobal(
        "URL",
        class extends URL {
          static createObjectURL = createObjectURL;
          static revokeObjectURL = revokeObjectURL;
        },
      );
      vi.stubGlobal(
        "Image",
        class {
          src = "";
          naturalHeight = 32;
          get naturalWidth() {
            return this.src === "blob:static" ? 16 : decodedWidth;
          }
          decode() {
            return Promise.resolve();
          }
        },
      );

      const { result, unmount } = renderHook(() =>
        useSpritePack(true, { animateTerrain: true }),
      );
      if (decodedWidth === animation.width) {
        await waitFor(() =>
          expect(result.current?.animation?.image).toBe("blob:animation"),
        );
      } else {
        await waitFor(() =>
          expect(revokeObjectURL).toHaveBeenCalledWith("blob:animation"),
        );
        expect(result.current?.animation).toBeUndefined();
      }
      expect(result.current?.image).toBe("blob:static");
      expect(fetchAtlas.mock.calls.map(([url]) => url)).toEqual([
        "/client-sprites/manifest.json",
        `/client-sprites/${pack.atlas}`,
        `/client-sprites/${animation.atlas}`,
      ]);
      unmount();
      expect(revokeObjectURL.mock.calls.flat().sort()).toEqual([
        "blob:animation",
        "blob:static",
      ]);
    },
  );
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
