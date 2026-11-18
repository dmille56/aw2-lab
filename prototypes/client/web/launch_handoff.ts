import { MATCH_ID } from "./state";

type Handoff = { match_id: string; token: string };

/** Erase the one-use capability before any request, without persisting tokens. */
export async function claimLocalLaunch(): Promise<Handoff | null> {
  const hash = new URLSearchParams(window.location.hash.slice(1));
  const ticket = hash.get("launch");
  if (ticket === null) return null;
  window.history.replaceState(
    null,
    "",
    window.location.pathname + window.location.search,
  );
  if (!/^[A-Za-z0-9_-]{32,128}$/.test(ticket))
    throw new Error(
      "Invalid local launch link. Use a new link from the match helper.",
    );
  const response = await fetch("/local-launch/claim", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticket }),
    cache: "no-store",
  });
  if (!response.ok)
    throw new Error(
      "Local launch link expired or already used. Use a new link or connect manually.",
    );
  const data: unknown = await response.json();
  if (
    !data ||
    typeof data !== "object" ||
    !("match_id" in data) ||
    !("token" in data) ||
    typeof data.match_id !== "string" ||
    !MATCH_ID.test(data.match_id) ||
    typeof data.token !== "string" ||
    !/^[^\s]{32,128}$/.test(data.token)
  )
    throw new Error("Invalid local launch response.");
  return { match_id: data.match_id, token: data.token };
}
