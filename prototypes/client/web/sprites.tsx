import { useEffect, useState } from "react";
import { getApiBase } from "./transport";

export interface SpriteRegion {
  x: number;
  y: number;
  width: number;
  height: number;
}
export interface SpritePack {
  width: number;
  height: number;
  units: Record<string, SpriteRegion>;
  terrain: Record<string, SpriteRegion>;
  portraits?: Record<string, SpriteRegion>;
  image: string;
}
interface Manifest extends Omit<SpritePack, "image"> {
  kind: "aw2-client-sprites";
  version: 1;
  atlas: string;
}
export function validateSpriteManifest(value: unknown): Manifest {
  if (!value || typeof value !== "object")
    throw new Error("No local sprite pack configured.");
  const m = value as Record<string, unknown>;
  const dimension = (n: unknown): n is number =>
    Number.isInteger(n) && Number(n) > 0 && Number(n) <= 4096;
  if (
    m.kind !== "aw2-client-sprites" ||
    m.version !== 1 ||
    !dimension(m.width) ||
    !dimension(m.height) ||
    typeof m.atlas !== "string" ||
    !/^atlas-[0-9a-f]{64}\.png$/.test(m.atlas)
  )
    throw new Error("Unsupported local sprite pack.");
  const collections = [
    { value: m.units, portraits: false },
    { value: m.terrain, portraits: false },
    ...(m.portraits === undefined
      ? []
      : [{ value: m.portraits, portraits: true }]),
  ];
  for (const { value: collection, portraits } of collections) {
    if (
      !collection ||
      typeof collection !== "object" ||
      Array.isArray(collection) ||
      Object.keys(collection).length > 256
    )
      throw new Error("Invalid sprite regions.");
    for (const [key, raw] of Object.entries(collection)) {
      const validKey = portraits
        ? /^(?:[0-9]|1[0-8])$/.test(key)
        : /^\d{1,2}:[0-5]$/.test(key);
      if (!validKey || !raw || typeof raw !== "object")
        throw new Error("Invalid sprite region.");
      const r = raw as Record<string, unknown>;
      if (
        !Number.isInteger(r.x) ||
        !Number.isInteger(r.y) ||
        Number(r.x) < 0 ||
        Number(r.y) < 0 ||
        !dimension(r.width) ||
        !dimension(r.height) ||
        r.width > (portraits ? 48 : 32) ||
        r.height > 32 ||
        Number(r.x) + r.width > m.width ||
        Number(r.y) + r.height > m.height
      )
        throw new Error("Sprite region outside atlas.");
    }
  }
  return value as Manifest;
}
export function useSpritePack(enabled: boolean) {
  const [pack, setPack] = useState<SpritePack | null>(null);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let image: string | null = null;
    const load = async () => {
      try {
        const base = await getApiBase();
        const options = {
          signal: AbortSignal.any([
            controller.signal,
            AbortSignal.timeout(5000),
          ]),
        };
        const response = await fetch(
          `${base}/client-sprites/manifest.json`,
          options,
        );
        if (!response.ok) return;
        const manifest = validateSpriteManifest(await response.json());
        const atlas = await fetch(
          `${base}/client-sprites/${manifest.atlas}`,
          options,
        );
        if (!atlas.ok) return;
        const blob = await atlas.blob();
        if (controller.signal.aborted) return;
        image = URL.createObjectURL(blob);
        const bitmap = new Image();
        bitmap.src = image;
        await bitmap.decode();
        if (
          !controller.signal.aborted &&
          bitmap.naturalWidth === manifest.width &&
          bitmap.naturalHeight === manifest.height
        )
          setPack({ ...manifest, image });
      } catch {
        // An absent or invalid pack leaves the readable symbolic board available.
      }
    };
    void load();
    return () => {
      controller.abort();
      if (image) URL.revokeObjectURL(image);
      setPack(null);
    };
  }, [enabled]);
  return pack;
}
export function Sprite({
  pack,
  region,
  className,
}: {
  pack: SpritePack;
  region: SpriteRegion;
  className: string;
}) {
  const cell = (n: number) => `calc(var(--cell) * ${n / 16})`;
  return (
    <span
      aria-hidden="true"
      className={`sprite ${className}`}
      style={{
        width: cell(region.width),
        height: cell(region.height),
        backgroundImage: `url("${pack.image}")`,
        backgroundSize: `${cell(pack.width)} ${cell(pack.height)}`,
        backgroundPosition: `${cell(-region.x)} ${cell(-region.y)}`,
      }}
    />
  );
}
