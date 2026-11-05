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
