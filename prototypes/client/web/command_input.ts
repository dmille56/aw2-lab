import type { components } from "./generated/api";

export type GameplayAction =
  components["schemas"]["GameplayCommandRequest"]["action"];
export type Coordinate = components["schemas"]["Coordinate"];
export type PropertyState = components["schemas"]["PropertyState"];

// The current purchase executor accepts production bases only (terrain class 14).
export const PRODUCTION_BASE_TERRAIN_CLASS = 14;

export function supportedProductionProperties(
  properties: PropertyState[],
  playerSlot: number,
): PropertyState[] {
  return properties.filter(
    (property) =>
      property.owner_slot === playerSlot &&
      property.terrain_class === PRODUCTION_BASE_TERRAIN_CLASS,
  );
}

export function parseCoordinate(
  value: string,
  width: number,
  height: number,
): Coordinate {
  const match = /^(0|[1-9]\d*),(0|[1-9]\d*)$/.exec(value.trim());
  if (!match)
    throw new Error("Enter a coordinate as x,y using nonnegative integers.");
  const point = {
    contract_version: 1 as const,
    x: Number(match[1]),
    y: Number(match[2]),
  };
  if (point.x >= width || point.y >= height)
    throw new Error(
      `Coordinate ${value} is outside the ${width}×${height} map.`,
    );
  return point;
}

export function parsePath(
  value: string,
  start: Coordinate,
  width: number,
  height: number,
): Coordinate[] {
  const text = value.trim();
  if (!text) return [];
  const tokens = text.split(/\s+/);
  if (tokens.length > 4096)
    throw new Error("A path may contain at most 4096 coordinates.");
  const points: Coordinate[] = [];
  let previous = start;
  for (const token of tokens) {
    const point = parseCoordinate(token, width, height);
    if (Math.abs(previous.x - point.x) + Math.abs(previous.y - point.y) !== 1)
      throw new Error(
        `Path step ${token} must be adjacent to ${previous.x},${previous.y}.`,
      );
    points.push(point);
    previous = point;
  }
  return points;
}
