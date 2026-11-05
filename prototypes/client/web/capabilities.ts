import validateSchema from "./generated/validate-capabilities.js";
import type { components } from "./generated/api";

export type CapabilitiesResponse =
  components["schemas"]["CapabilitiesResponse"];

const record = (value: unknown): Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};

function requireVersion(
  value: Record<string, unknown>,
  field: string,
  version: number,
  description: string,
) {
  const versions = value[field];
  if (!Array.isArray(versions) || !versions.every(Number.isInteger))
    throw new Error(
      `Server capabilities do not advertise valid ${description} versions.`,
    );
  if (!versions.includes(version)) {
    throw new Error(
      `Unsupported ${description} version. This client supports ${version}; the server advertises ${versions.join(", ") || "none"}.`,
    );
  }
}

function requireAvailable(name: string, value: unknown) {
  const feature = record(value);
  if (!feature.implemented)
    throw new Error(
      `The server does not implement required capability: ${name}.`,
    );
  if (!feature.available) {
    const reason = feature.unavailable_reason;
    throw new Error(
      `The server reports ${name} unavailable${typeof reason === "string" ? `: ${reason}` : "."}`,
    );
  }
}

export function validateCapabilitiesResponse(
  value: unknown,
): CapabilitiesResponse {
  const response = record(value);
  if (response.contract_version !== 1) {
    throw new Error(
      `Unsupported API contract version from capabilities: ${String(response.contract_version)}; this client supports version 1.`,
    );
  }
  requireVersion(
    response,
    "supported_game_contract_versions",
    1,
    "game contract",
  );
  requireVersion(
    response,
    "supported_match_observation_schema_versions",
    1,
    "match observation schema",
  );
  requireVersion(
    response,
    "supported_game_state_schema_versions",
    4,
    "game-state schema",
  );
  if (!validateSchema(value))
    throw new Error(
      "Server returned a malformed capabilities response for API v1.",
    );

  const capabilities = value as CapabilitiesResponse;
  requireAvailable(
    "match state",
    capabilities.operations.find(({ name }) => name === "state"),
  );
  requireAvailable("HTTP SSE", capabilities.http_sse);
  requireAvailable(
    "match event stream",
    capabilities.operations.find(({ name }) => name === "events"),
  );
  return capabilities;
}
