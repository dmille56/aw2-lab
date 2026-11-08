import type { components } from "./generated/api";

export type GameplayAction =
  components["schemas"]["GameplayCommandRequest"]["action"];
export type Coordinate = components["schemas"]["Coordinate"];
export type PropertyState = components["schemas"]["PropertyState"];
export type ProductionFacility =
  components["schemas"]["ProductionFacilityCapabilities"];

export function supportedProductionProperties(
  properties: PropertyState[],
  playerSlot: number,
  facilities: ProductionFacility[],
): PropertyState[] {
  const terrainClasses = new Set(
    facilities.map((facility) => facility.terrain_class),
  );
  return properties.filter(
    (property) =>
      property.owner_slot === playerSlot &&
      terrainClasses.has(property.terrain_class),
  );
}
