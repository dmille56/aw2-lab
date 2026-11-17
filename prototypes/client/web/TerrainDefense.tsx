import catalog from "./catalog.json";

export function terrainDefenseRating(
  terrainClass: number | undefined,
): number | null {
  if (
    terrainClass === undefined ||
    !Number.isInteger(terrainClass) ||
    terrainClass < 0
  )
    return null;
  const rating = catalog.combat.terrain_stars[terrainClass];
  return Number.isInteger(rating) && rating >= 0 && rating <= 4 ? rating : null;
}

export function TerrainDefense({
  terrainClass,
}: {
  terrainClass: number | undefined;
}) {
  const rating = terrainDefenseRating(terrainClass);
  return rating === null ? (
    <span data-terrain-defense="unknown">Unavailable</span>
  ) : (
    <span data-terrain-defense={rating}>
      {rating}/4{" "}
      <span aria-hidden="true">
        {"★".repeat(rating)}
        {"☆".repeat(4 - rating)}
      </span>
    </span>
  );
}
