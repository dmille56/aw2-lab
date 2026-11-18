import { afterEach, describe, expect, it, vi } from "vitest";
import { claimLocalLaunch } from "../web/launch_handoff";

afterEach(() => {
  window.history.replaceState(null, "", "/client/");
  vi.unstubAllGlobals();
});

describe("local browser handoff", () => {
  it("does nothing without a launch ticket", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    expect(await claimLocalLaunch()).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("removes the fragment before claiming and keeps credentials in memory", async () => {
    window.history.replaceState(null, "", "/client/#launch=" + "t".repeat(40));
    const handoff = {
      match_id: "00000000-0000-4000-8000-000000000001",
      token: "p".repeat(40),
    };
    const fetcher = vi.fn(() => {
      expect(window.location.hash).toBe("");
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(handoff),
      });
    });
    vi.stubGlobal("fetch", fetcher);
    expect(await claimLocalLaunch()).toEqual(handoff);
    expect(fetcher).toHaveBeenCalledWith(
      "/local-launch/claim",
      expect.objectContaining({ method: "POST", cache: "no-store" }),
    );
  });
  it("reports expired links without exposing response bodies", async () => {
    window.history.replaceState(null, "", "/client/#launch=" + "t".repeat(40));
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ ok: false })),
    );
    await expect(claimLocalLaunch()).rejects.toThrow("expired or already used");
    expect(window.location.hash).toBe("");
  });
});
