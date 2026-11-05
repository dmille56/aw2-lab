import { afterEach, expect, it, vi } from "vitest";
import { MatchSession } from "../web/session";
import fixture from "./fixtures/state.json";

const sessions: MatchSession[] = [];
const session = () => {
  const value = new MatchSession();
  sessions.push(value);
  return value;
};
const pending = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};
const response = (value: unknown) => new Response(JSON.stringify(value));
function server(
  state: () => Response | Promise<Response>,
  screenshot?: () => Response | Promise<Response>,
) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init: RequestInit) => {
      if (url.endsWith("/events"))
        return new Promise<Response>((_, reject) => {
          init.signal?.addEventListener(
            "abort",
            () => reject(new DOMException("Aborted", "AbortError")),
            { once: true },
          );
        });
      if (url.includes("/screenshot")) return screenshot?.();
      return state();
    }),
  );
}
afterEach(() => {
  sessions.splice(0).forEach((item) => item.disconnect());
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("ignores a late state response from a replaced connection", async () => {
  const first = pending<Response>();
  let calls = 0;
  server(() => (++calls === 1 ? first.promise : response(fixture)));
  const view = session();
  const old = view.connect(fixture.summary.match_id, "old");
  await view.connect(fixture.summary.match_id, "new");
  const stale = structuredClone(fixture);
  stale.summary.revision = stale.observation.revision = 99;
  first.resolve(response(stale));
  await old;
  expect(view.getSnapshot().snapshot?.summary.revision).toBe(1);
});
it("clears match data and aborts requests after authorization loss", async () => {
  let revoked = false;
  server(() =>
    revoked ? new Response(null, { status: 403 }) : response(fixture),
  );
  const view = session();
  await view.connect(fixture.summary.match_id, "private");
  revoked = true;
  await view.refreshCurrent();
  expect(view.getSnapshot()).toMatchObject({
    snapshot: null,
    connected: false,
    ready: false,
    image: null,
    status: "Authorization lost · reconnect required",
  });
});
it("discards a snapshot import completed after disconnect", async () => {
  const text = pending<string>();
  const file = new File([], "state.json");
  Object.defineProperty(file, "text", { value: () => text.promise });
  const view = session();
  const opening = view.openSnapshot(file);
  view.disconnect();
  text.resolve(JSON.stringify(fixture));
  await opening;
  expect(view.getSnapshot().snapshot).toBeNull();
});
it("discards a screenshot completed after the displayed revision changes", async () => {
  let current = structuredClone(fixture);
  const image = pending<Response>();
  server(
    () => response(current),
    () => image.promise,
  );
  const view = session();
  await view.connect(fixture.summary.match_id, "private");
  const loading = view.loadScreenshot();
  current = structuredClone(fixture);
  current.summary.revision = current.observation.revision = 2;
  current.observation.game_state.frame = 124;
  await view.refreshCurrent();
  image.resolve(
    new Response(new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]), {
      headers: {
        "Content-Type": "image/png",
        "X-AW2-Match-ID": fixture.summary.match_id,
        "X-AW2-Revision": "1",
        "X-AW2-Frame": String(fixture.observation.game_state.frame),
      },
    }),
  );
  await loading;
  expect(view.getSnapshot().snapshot?.summary.revision).toBe(2);
  expect(view.getSnapshot().image).toBeNull();
});
