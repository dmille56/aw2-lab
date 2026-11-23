import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { getApiBase } from "./transport";

export interface SpriteRegion {
  x: number;
  y: number;
  width: number;
  height: number;
}
interface AtlasSize {
  width: number;
  height: number;
}
interface SpriteAtlas extends AtlasSize {
  image: string;
}
type TerrainCollection = "terrain" | "terrain_variants";
interface AnimationManifest extends AtlasSize {
  atlas: string;
  cycle_frames: number;
  frames: Partial<Record<TerrainCollection, Record<string, SpriteRegion[]>>>;
}
interface TerrainAnimation extends AnimationManifest, SpriteAtlas {}

interface FactorySmoke {
  frames_per_phase: number;
  frames: SpriteRegion[];
}

export interface SpritePack extends SpriteAtlas {
  units: Record<string, SpriteRegion>;
  terrain: Record<string, SpriteRegion>;
  portraits?: Record<string, SpriteRegion>;
  terrain_variants?: Record<string, SpriteRegion>;
  animation?: TerrainAnimation;
  factory_smoke?: FactorySmoke;
}
interface Manifest extends Omit<
  SpritePack,
  "image" | "animation" | "factory_smoke"
> {
  kind: "aw2-client-sprites";
  version: 1;
  atlas: string;
  animation?: unknown;
  factory_smoke?: unknown;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);
const boundedInteger = (n: unknown, min: number, max: number): n is number =>
  typeof n === "number" && Number.isInteger(n) && n >= min && n <= max;
const dimension = (n: unknown): n is number => boundedInteger(n, 1, 4096);
const armyKey = (key: string) => /^\d{1,2}:[0-5]$/.test(key);
const variantKey = (key: string) =>
  /^(?:1|2|3|4|5|7|12|13|15|16|19):(?:0|[1-9][0-9]{0,3})$/.test(key) &&
  Number(key.split(":")[1]) <= 1023;

function regionInAtlas(
  raw: unknown,
  { width, height }: AtlasSize,
  max: number,
): raw is SpriteRegion {
  return (
    isRecord(raw) &&
    boundedInteger(raw.width, 1, max) &&
    boundedInteger(raw.height, 1, max) &&
    boundedInteger(raw.x, 0, width - raw.width) &&
    boundedInteger(raw.y, 0, height - raw.height)
  );
}
export function validateSpriteManifest(value: unknown): Manifest {
  if (!isRecord(value)) throw new Error("No local sprite pack configured.");
  const m = value;
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
    { value: m.units, portraits: false, variants: false },
    { value: m.terrain, portraits: false, variants: false },
    ...(m.portraits === undefined
      ? []
      : [{ value: m.portraits, portraits: true, variants: false }]),
    ...(m.terrain_variants === undefined
      ? []
      : [{ value: m.terrain_variants, portraits: false, variants: true }]),
  ];
  for (const { value: collection, portraits, variants } of collections) {
    if (!isRecord(collection) || Object.keys(collection).length > 256)
      throw new Error("Invalid sprite regions.");
    for (const [key, raw] of Object.entries(collection)) {
      const validKey = portraits
        ? /^(?:[0-9]|1[0-8])$/.test(key)
        : variants
          ? variantKey(key)
          : armyKey(key);
      if (!validKey) throw new Error("Invalid sprite region.");
      if (
        !regionInAtlas(
          raw,
          { width: m.width, height: m.height },
          portraits ? 48 : 32,
        )
      )
        throw new Error("Sprite region outside atlas.");
    }
  }
  return value as unknown as Manifest;
}

export function validateTerrainAnimation(
  value: unknown,
): AnimationManifest | undefined {
  if (!isRecord(value)) return;
  const { atlas, atlas_sha256, width, height, cycle_frames, frames } = value;
  if (
    typeof atlas_sha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(atlas_sha256) ||
    atlas !== `animation-${atlas_sha256}.png` ||
    !dimension(width) ||
    !dimension(height) ||
    !boundedInteger(cycle_frames, 1, 600) ||
    !isRecord(frames)
  )
    return;

  const animation: AnimationManifest = {
    atlas,
    width,
    height,
    cycle_frames,
    frames: {},
  };
  let total = 0;
  for (const [kind, collection] of Object.entries(frames)) {
    if (kind !== "terrain" && kind !== "terrain_variants") return;
    if (!isRecord(collection) || Object.keys(collection).length > 256) return;
    const regions: Record<string, SpriteRegion[]> = {};
    for (const [key, sequence] of Object.entries(collection)) {
      const validKey =
        kind === "terrain_variants" ? variantKey(key) : armyKey(key);
      if (!validKey || !Array.isArray(sequence) || sequence.length > 16) return;
      total += sequence.length;
      if (total > 2048) return;
      const checked: SpriteRegion[] = [];
      for (const frame of sequence as unknown[]) {
        if (
          !regionInAtlas(frame, animation, 32) ||
          frame.width !== 16 ||
          frame.height !== 32
        )
          return;
        checked.push(frame);
      }
      if (checked.length > 1) regions[key] = checked;
    }
    if (Object.keys(regions).length) animation.frames[kind] = regions;
  }
  if (Object.keys(animation.frames).length) return animation;
}

export function validateFactorySmoke(
  value: unknown,
  atlas: AtlasSize,
): FactorySmoke | undefined {
  if (
    !isRecord(value) ||
    !boundedInteger(value.frames_per_phase, 1, 600) ||
    !Array.isArray(value.frames) ||
    !boundedInteger(value.frames.length, 2, 16)
  )
    return;
  const frames: unknown[] = value.frames;
  if (
    frames.every(
      (frame): frame is SpriteRegion =>
        regionInAtlas(frame, atlas, 16) &&
        frame.width === 16 &&
        frame.height === 16,
    )
  )
    return { frames_per_phase: value.frames_per_phase, frames };
}

export function terrainArtwork(
  pack: SpritePack | null,
  tile: {
    terrain_class: number;
    owner_slot: number;
    graphical_tile_id: number;
  },
) {
  if (!pack) return;
  // Terrain artwork is chosen per cell for every class that is not selected by army,
  // so each such cell uses its exact map variant when present: plains cells carry the
  // tip of the mountain range below them, and mountains, woods, roads, seas, and
  // shoals each have several shapes. Shoals have no representative sprite, so a
  // missing shoal variant stays symbolic instead of repeating a wrongly oriented tile.
  const variantKey = `${tile.terrain_class}:${tile.graphical_tile_id}`;
  const variant = pack.terrain_variants?.[variantKey];
  if (variant)
    return {
      region: variant,
      frames: pack.animation?.frames.terrain_variants?.[variantKey],
    };
  if (tile.terrain_class === 13) return;
  const armyKey = `${tile.terrain_class}:${tile.owner_slot}`;
  const region = pack.terrain[armyKey];
  if (region)
    return { region, frames: pack.animation?.frames.terrain?.[armyKey] };
}

export function useSpritePack(
  enabled: boolean,
  { animateTerrain = false } = {},
) {
  const [pack, setPack] = useState<SpritePack | null>(null);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    const images = new Set<string>();
    const requestOptions = () => ({
      signal: AbortSignal.any([controller.signal, AbortSignal.timeout(5000)]),
    });
    const loadAtlas = async (
      base: string,
      { atlas, width, height }: AtlasSize & { atlas: string },
    ) => {
      const options = requestOptions();
      const response = await fetch(`${base}/client-sprites/${atlas}`, options);
      if (!response.ok) return;
      const blob = await response.blob();
      if (options.signal.aborted) return;
      const image = URL.createObjectURL(blob);
      images.add(image);
      try {
        const bitmap = new Image();
        bitmap.src = image;
        await bitmap.decode();
        if (
          !options.signal.aborted &&
          bitmap.naturalWidth === width &&
          bitmap.naturalHeight === height
        )
          return image;
      } catch {
        // Keep the fallback if the image cannot be decoded.
      }
      if (images.delete(image)) URL.revokeObjectURL(image);
    };
    const load = async () => {
      try {
        const base = await getApiBase();
        const response = await fetch(
          `${base}/client-sprites/manifest.json`,
          requestOptions(),
        );
        if (!response.ok) return;
        const {
          animation: rawAnimation,
          factory_smoke: rawSmoke,
          ...manifest
        } = validateSpriteManifest(await response.json());
        const image = await loadAtlas(base, manifest);
        if (!image || controller.signal.aborted) return;
        const staticPack = {
          ...manifest,
          image,
          factory_smoke: animateTerrain
            ? validateFactorySmoke(rawSmoke, manifest)
            : undefined,
        };
        setPack(staticPack);

        const animation =
          animateTerrain && validateTerrainAnimation(rawAnimation);
        if (!animation) return;
        const animationImage = await loadAtlas(base, animation);
        if (animationImage && !controller.signal.aborted)
          setPack({
            ...staticPack,
            animation: { ...animation, image: animationImage },
          });
      } catch {
        // Keep symbolic or static artwork when an asset cannot be loaded.
      }
    };
    void load();
    return () => {
      controller.abort();
      for (const image of images) URL.revokeObjectURL(image);
      images.clear();
      setPack(null);
    };
  }, [enabled, animateTerrain]);
  return pack;
}

const TerrainFrame = createContext<number | null>(null);
const FactorySmokeFrame = createContext<number | null>(null);
const MIN_TERRAIN_FRAME_MS = 400;

function useAnimationFrame(cycleFrames: number | undefined, minimumMs = 0) {
  const [frame, setFrame] = useState<number | null>(null);
  useEffect(() => {
    if (!cycleFrames) return;
    const motion = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    let timer: number | undefined;
    const syncMotion = () => {
      window.clearInterval(timer);
      if (motion?.matches) {
        setFrame(null);
        return;
      }
      setFrame(0);
      timer = window.setInterval(
        () => setFrame((current) => (current ?? 0) + 1),
        Math.max(minimumMs, (cycleFrames * 1000) / 60),
      );
    };
    syncMotion();
    motion?.addEventListener("change", syncMotion);
    return () => {
      window.clearInterval(timer);
      motion?.removeEventListener("change", syncMotion);
    };
  }, [cycleFrames, minimumMs]);
  return cycleFrames ? frame : null;
}

export function TerrainAnimationClock({
  cycleFrames,
  smokeFramesPerPhase,
  children,
}: {
  cycleFrames?: number;
  smokeFramesPerPhase?: number;
  children: ReactNode;
}) {
  const frame = useAnimationFrame(cycleFrames, MIN_TERRAIN_FRAME_MS);
  const smokeFrame = useAnimationFrame(smokeFramesPerPhase);
  return (
    <TerrainFrame.Provider value={frame}>
      <FactorySmokeFrame.Provider value={smokeFrame}>
        {children}
      </FactorySmokeFrame.Provider>
    </TerrainFrame.Provider>
  );
}

export function FactorySmokeSprite({
  pack,
  smoke,
}: {
  pack: SpritePack;
  smoke: FactorySmoke;
}) {
  const frame = useContext(FactorySmokeFrame);
  if (frame === null) return null;
  return (
    <Sprite
      pack={pack}
      region={smoke.frames[frame % smoke.frames.length]}
      className="sprite-factory-smoke"
    />
  );
}

export function AnimatedTerrainSprite({
  pack,
  animation,
  region,
  frames,
}: {
  pack: SpritePack;
  animation: TerrainAnimation;
  region: SpriteRegion;
  frames: SpriteRegion[];
}) {
  const frame = useContext(TerrainFrame);
  if (frame === null)
    return <Sprite pack={pack} region={region} className="sprite-terrain" />;
  return (
    <Sprite
      pack={animation}
      region={frames[frame % frames.length]}
      className="sprite-terrain"
    />
  );
}

export function Sprite({
  pack,
  region,
  className,
}: {
  pack: SpriteAtlas;
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
