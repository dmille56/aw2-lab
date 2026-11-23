import validateIdentity from "./generated/validate-identity.js";
import validateReceipt from "./generated/validate-receipt.js";
import validateResult from "./generated/validate-result.js";
import type { components } from "./generated/api";
export type MatchIdentity = components["schemas"]["MatchIdentityResponse"];
import { getApiBase } from "./transport";
import { MATCH_ID, validateState, type StateResponse } from "./state";
import { validateCapabilitiesResponse } from "./capabilities";
import type { CapabilitiesResponse } from "./capabilities";

type GameplayAction = components["schemas"]["GameplayCommandRequest"]["action"];
type GameplayCommandRequest = components["schemas"]["GameplayCommandRequest"];
type CommandReceipt = components["schemas"]["CommandReceipt"];
type CommandResult = components["schemas"]["CommandResult"];
type CommandStatus = components["schemas"]["CommandStatus"];

export interface CommandProgress {
  request: GameplayCommandRequest;
  receipt: CommandReceipt | null;
  result: CommandResult | null;
  phase: "submitting" | "uncertain" | CommandStatus;
}

export const commandIsPending = (command: CommandProgress | null) =>
  !!command &&
  ["submitting", "uncertain", "queued", "running"].includes(command.phase);

export function commandNeedsRefresh(
  command: CommandProgress | null,
  snapshot: StateResponse | null,
) {
  const revision = command?.result?.resulting_revision;
  return (
    typeof revision === "number" &&
    (snapshot?.summary.revision ?? -1) < revision
  );
}

interface Connection {
  id: string;
  token: string;
  abort: AbortController;
  refreshing: Promise<void> | null;
  again: boolean;
}
export interface ViewState {
  snapshot: StateResponse | null;
  identity: MatchIdentity | null;
  capabilities: CapabilitiesResponse | null;
  command: CommandProgress | null;
  connected: boolean;
  ready: boolean;
  status: string;
  error: string;
  image: string | null;
  imageLabel: string;
}
const imageLabel = "Optional image from the displayed committed revision.";
const requestTimeoutMs = 15_000;
const requestSignal = (connection: Connection) =>
  AbortSignal.any([
    connection.abort.signal,
    AbortSignal.timeout(requestTimeoutMs),
  ]);
export const message = (error: unknown) =>
  error instanceof Error ? error.message : String(error);
const aborted = (error: unknown) =>
  error instanceof Error && error.name === "AbortError";

class MatchRequestError extends Error {
  constructor(readonly status: number) {
    super(`Request failed (${status}). Check match access and server status.`);
  }
}

function retryableStatusError(error: unknown) {
  return (
    error instanceof TypeError ||
    (error instanceof Error && error.name === "TimeoutError") ||
    (error instanceof MatchRequestError &&
      (error.status === 408 || error.status === 429 || error.status >= 500))
  );
}

/** Owns credentials, cancellation and boundary synchronization independently of React. */
export class MatchSession {
  private connection: Connection | null = null;
  private generation = 0;
  private listeners = new Set<() => void>();
  private state: ViewState = {
    snapshot: null,
    identity: null,
    capabilities: null,
    command: null,
    connected: false,
    ready: false,
    status: "Open a snapshot or connect to a match",
    error: "",
    image: null,
    imageLabel,
  };
  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  private update(patch: Partial<ViewState>) {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((listener) => listener());
  }
  private clearImage() {
    if (this.state.image) URL.revokeObjectURL(this.state.image);
    this.update({ image: null, imageLabel });
  }
  disconnect = (status = "Disconnected") => {
    this.generation++;
    this.connection?.abort.abort();
    this.connection = null;
    this.clearImage();
    this.update({
      snapshot: null,
      identity: null,
      capabilities: null,
      command: null,
      connected: false,
      ready: false,
      status,
      error: "",
    });
  };
  private render(snapshot: StateResponse) {
    this.clearImage();
    this.update({ snapshot });
  }
  private async request(c: Connection, suffix: string, optional = false) {
    const apiBase = await getApiBase();
    const response = await fetch(`${apiBase}/v1/matches/${c.id}/${suffix}`, {
      headers: { Authorization: `Bearer ${c.token}` },
      signal: suffix === "events" ? c.abort.signal : requestSignal(c),
      cache: "no-store",
      credentials: "omit",
      redirect: "error",
    });
    if (response.status === 401 || response.status === 403) {
      if (this.connection === c)
        this.disconnect("Authorization lost · reconnect required");
      throw new Error("This credential no longer has access to the match.");
    }
    if (optional && response.status === 404) return response;
    if (!response.ok) throw new MatchRequestError(response.status);
    return response;
  }
  private async checkCapabilities(c: Connection) {
    const apiBase = await getApiBase();
    const response = await fetch(`${apiBase}/v1/capabilities`, {
      signal: requestSignal(c),
      cache: "no-store",
      credentials: "omit",
      redirect: "error",
    });
    if (!response.ok)
      throw new Error(
        `Capabilities request failed (${response.status}). Check server status and API compatibility.`,
      );
    return validateCapabilitiesResponse(await response.json());
  }
  private async refresh(c: Connection) {
    c.again = true;
    if (c.refreshing) return c.refreshing;
    c.refreshing = (async () => {
      while (c.again && this.connection === c) {
        c.again = false;
        const value = validateState(
          await (await this.request(c, "state")).json(),
        );
        if (value.summary.match_id !== c.id)
          throw new Error("Server returned a different match.");
        if (
          this.connection === c &&
          (!this.state.snapshot ||
            value.summary.revision >= this.state.snapshot.summary.revision)
        )
          this.render(value);
      }
    })();
    try {
      await c.refreshing;
    } finally {
      c.refreshing = null;
    }
  }
  private reconcileCommandEvent(c: Connection, data: string) {
    const command = this.state.command;
    if (this.connection !== c || !command || !commandIsPending(command)) return;
    let event: unknown;
    try {
      event = JSON.parse(data);
    } catch {
      return;
    }
    if (
      typeof event !== "object" ||
      event === null ||
      !("payload" in event) ||
      !validateResult(event.payload)
    )
      return;
    const result = event.payload as CommandResult;
    if (
      result.match_id !== c.id ||
      result.request_id !== command.request.request_id ||
      result.status === "queued" ||
      result.status === "running" ||
      (command.receipt && result.command_id !== command.receipt.command_id)
    )
      return;
    this.update({
      command: { ...command, result, phase: result.status },
      error: result.error?.message ?? "",
    });
  }
  private async follow(c: Connection) {
    let delay = 1000;
    while (this.connection === c) {
      try {
        const response = await this.request(c, "events");
        if (!response.body) throw new Error("Event stream unavailable");
        const reader = response.body
          .pipeThrough(new TextDecoderStream())
          .getReader();
        let buffer = "";
        try {
          await this.refresh(c);
          if (this.connection !== c) return;
          this.update({ status: "Live · observing committed match updates" });
          delay = 1000;
          while (this.connection === c) {
            const { value, done } = await reader.read();
            if (done) throw new Error("Event stream disconnected");
            buffer += value;
            if (buffer.length > 1048576)
              throw new Error("Event stream exceeded client limit");
            let end: number;
            while ((end = buffer.indexOf("\n\n")) !== -1) {
              const frame = buffer.slice(0, end);
              buffer = buffer.slice(end + 2);
              const lines = frame.split("\n");
              const data = lines
                .filter((line) => line.startsWith("data:"))
                .map((line) => line.slice(5).trimStart())
                .join("\n");
              if (data) {
                if (lines.includes("event: command.updated"))
                  this.reconcileCommandEvent(c, data);
                await this.refresh(c);
              }
            }
          }
        } finally {
          await reader.cancel().catch(() => {});
        }
      } catch {
        if (this.connection !== c || c.abort.signal.aborted) return;
        this.update({ status: `Disconnected · retrying in ${delay / 1000}s` });
        await new Promise<void>((resolve) => {
          const finish = () => {
            clearTimeout(timer);
            c.abort.signal.removeEventListener("abort", finish);
            resolve();
          };
          const timer = setTimeout(finish, delay);
          c.abort.signal.addEventListener("abort", finish, { once: true });
        });
        delay = Math.min(delay * 2, 15000);
      }
    }
  }
  connect = async (id: string, token: string) => {
    id = id.trim().toLowerCase();
    this.disconnect("Connecting…");
    if (!MATCH_ID.test(id)) {
      this.update({ error: "Enter a valid match UUID." });
      return;
    }
    const c: Connection = {
      id,
      token,
      abort: new AbortController(),
      refreshing: null,
      again: false,
    };
    this.connection = c;
    this.update({ connected: true });
    try {
      const capabilities = await this.checkCapabilities(c);
      if (this.connection !== c) return;
      this.update({ capabilities });
      const response = await this.request(c, "identity", true);
      if (this.connection !== c) return;
      if (response.ok) {
        const value: unknown = await response.json();
        if (!validateIdentity(value))
          throw new Error("Server returned an invalid match identity.");
        const identity = value as MatchIdentity;
        if (
          identity.match_id !== c.id ||
          (identity.role === "player"
            ? identity.player_slot === null
            : identity.player_slot !== null)
        )
          throw new Error("Server returned an inconsistent match identity.");
        if (this.connection !== c) return;
        this.update({ identity });
      }
      await this.refresh(c);
      if (this.connection !== c) return;
      this.update({ ready: true });
      void this.follow(c);
    } catch (error) {
      if (this.connection !== c) return;
      this.disconnect("Connection failed");
      if (!aborted(error)) this.update({ error: message(error) });
    }
  };
  refreshCurrent = async () => {
    const c = this.connection;
    if (!c) return;
    try {
      await this.refresh(c);
      if (this.connection === c) this.update({ error: "" });
    } catch (error) {
      if (this.connection === c && !aborted(error))
        this.update({ error: message(error) });
    }
  };
  recoverCurrent = async () => {
    const previous = this.connection;
    if (!previous || !this.state.snapshot) return;
    const c: Connection = {
      id: previous.id,
      token: previous.token,
      abort: new AbortController(),
      refreshing: null,
      again: false,
    };
    this.connection = c;
    previous.abort.abort();
    const command = this.state.command;
    this.update({
      ready: false,
      status: "Recovering match connection…",
      error: "",
      command:
        command?.phase === "submitting"
          ? { ...command, phase: "uncertain" }
          : command,
    });
    try {
      await this.refresh(c);
      if (this.connection !== c) return;
      this.update({ ready: true, status: "Match state refreshed" });
      void this.follow(c);
      if (command?.receipt && (commandIsPending(command) || !command.result))
        void this.pollCommand(c, command.receipt, Infinity);
    } catch (error) {
      if (this.connection !== c || aborted(error)) return;
      this.update({
        status: "Match recovery could not reach the server",
        error: `Check that the match host is running, then choose Recover session again. ${message(error)}`,
      });
    }
  };
  submitAction = async (action: GameplayAction, expectedRevision: number) => {
    const c = this.connection;
    const snapshot = this.state.snapshot;
    const identity = this.state.identity;
    if (!c || !snapshot || !this.state.ready) return;
    if (commandIsPending(this.state.command)) {
      this.update({
        error: "Resolve the pending command before submitting another action.",
      });
      return;
    }
    if (commandNeedsRefresh(this.state.command, snapshot)) {
      this.update({
        error: "Waiting for the board to reach the last command's revision.",
      });
      return;
    }
    if (snapshot.summary.revision !== expectedRevision) {
      this.update({
        error:
          "This action preview is stale. Refresh or rebase it to the current revision.",
      });
      return;
    }
    if (
      !identity ||
      identity.role !== "player" ||
      identity.player_slot === null
    ) {
      this.update({
        error: "Gameplay commands require an authenticated player slot.",
      });
      return;
    }
    const request: GameplayCommandRequest = {
      contract_version: 1,
      request_id: crypto.randomUUID(),
      expected_revision: expectedRevision,
      action,
    };
    await this.transmitAction(c, request);
  };
  retryUncertainAction = async () => {
    const c = this.connection;
    const command = this.state.command;
    if (
      !c ||
      !this.state.ready ||
      !command ||
      command.phase !== "uncertain" ||
      command.receipt
    )
      return;
    await this.transmitAction(c, command.request);
  };
  checkCommandStatus = async () => {
    const c = this.connection;
    const command = this.state.command;
    if (!c || !this.state.ready || !command) return;
    if (!command.receipt) {
      if (command.phase === "uncertain") await this.retryUncertainAction();
      return;
    }
    await this.pollCommand(c, command.receipt, 1);
  };
  private async transmitAction(c: Connection, request: GameplayCommandRequest) {
    this.update({
      command: { request, receipt: null, result: null, phase: "submitting" },
      error: "",
    });
    const submitting = () =>
      this.connection === c &&
      this.state.command?.request.request_id === request.request_id &&
      this.state.command.phase === "submitting";
    try {
      const apiBase = await getApiBase();
      const response = await fetch(`${apiBase}/v1/matches/${c.id}/commands`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${c.token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(request),
        signal: requestSignal(c),
        cache: "no-store",
        credentials: "omit",
        redirect: "error",
      });
      if (!submitting()) return;
      if (response.status === 401 || response.status === 403) {
        this.disconnect("Authorization lost · reconnect required");
        throw new Error("This credential no longer has access to the match.");
      }
      if (!response.ok) {
        const detail = await this.readError(response);
        if (!submitting()) return;
        if (response.status === 408 || response.status >= 500)
          throw new Error(detail);
        this.update({
          command: { request, receipt: null, result: null, phase: "rejected" },
          error: detail,
        });
        return;
      }
      const value: unknown = await response.json();
      if (!submitting()) return;
      if (!validateReceipt(value)) throw new Error("Invalid command receipt");
      const receipt = value as CommandReceipt;
      if (
        receipt.match_id !== c.id ||
        receipt.request_id !== request.request_id
      )
        throw new Error("Command receipt does not match this request.");
      this.update({
        command: { request, receipt, result: null, phase: receipt.status },
      });
      await this.pollCommand(c, receipt, Infinity);
    } catch (error) {
      if (!submitting() || aborted(error)) return;
      this.update({
        command: { request, receipt: null, result: null, phase: "uncertain" },
        error: `The command submission outcome is unknown (${message(error)}). Retry safely to resend the identical request ID and payload.`,
      });
    }
  }
  private async pollCommand(
    c: Connection,
    receipt: CommandReceipt,
    attempts: number,
  ) {
    let delay = 500;
    const current = () => {
      const command = this.state.command;
      return this.connection === c &&
        command?.request.request_id === receipt.request_id &&
        (!command.result || commandIsPending(command))
        ? command
        : null;
    };
    for (let index = 0; index < attempts && this.connection === c; index++) {
      if (!current()) return;
      try {
        const response = await this.request(
          c,
          `commands/${receipt.command_id}`,
        );
        const value: unknown = await response.json();
        const command = current();
        if (!command) return;
        if (!validateResult(value))
          throw new Error("Invalid command status response");
        const result = value as CommandResult;
        if (
          result.match_id !== c.id ||
          result.command_id !== receipt.command_id ||
          result.request_id !== receipt.request_id
        )
          throw new Error(
            "Command status does not match the accepted receipt.",
          );
        const updated = { ...command, result, phase: result.status };
        if (
          !commandIsPending(updated) ||
          (commandIsPending(command) &&
            !(command.phase === "running" && result.status === "queued"))
        )
          this.update({
            command: updated,
            error: result.error?.message ?? "",
          });
        if (!commandIsPending(updated)) {
          await this.refresh(c).catch((error: unknown) => {
            if (this.connection === c && !aborted(error))
              this.update({
                error: `Refresh after command failed: ${message(error)}`,
              });
          });
          return;
        }
        delay = 500;
      } catch (error) {
        if (!current() || aborted(error)) return;
        this.update({
          error: `Command accepted; status could not be confirmed: ${message(error)}`,
        });
        if (index + 1 >= attempts || !retryableStatusError(error)) return;
        delay = Math.min(delay * 2, 5000);
      }
      if (index + 1 < attempts)
        await new Promise<void>((resolve) => setTimeout(resolve, delay));
    }
  }
  private async readError(response: Response) {
    try {
      const body: unknown = await response.json();
      if (
        typeof body === "object" &&
        body !== null &&
        "error" in body &&
        typeof body.error === "object" &&
        body.error !== null &&
        "message" in body.error &&
        typeof body.error.message === "string"
      )
        return `${response.status}: ${body.error.message}`;
    } catch {
      // Use a stable status message when the server returns no JSON error body.
    }
    return `Command request failed (${response.status}). Refresh state and review the server response.`;
  }
  openSnapshot = async (file: File) => {
    this.disconnect("Opening snapshot…");
    const generation = this.generation;
    try {
      if (file.size > 5 * 1024 * 1024)
        throw new Error("Snapshot exceeds the 5 MiB limit.");
      const value = validateState(JSON.parse(await file.text()));
      if (generation !== this.generation) return;
      this.render(value);
      this.update({ status: "Snapshot · read only" });
    } catch (error) {
      if (generation === this.generation)
        this.update({
          status: "Snapshot could not be opened",
          error: message(error),
        });
    }
  };
  exportSnapshot = () => {
    const snapshot = this.state.snapshot;
    if (!snapshot) return;
    const output = {
      contract_version: snapshot.contract_version,
      summary: snapshot.summary,
      settled: snapshot.settled,
      observation: snapshot.observation,
    };
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(output, null, 2)], { type: "application/json" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `aw2-${snapshot.summary.match_id}-revision-${snapshot.summary.revision}.json`;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  loadScreenshot = async () => {
    const c = this.connection,
      revision = this.state.snapshot?.summary.revision,
      frame = this.state.snapshot?.observation?.game_state.frame;
    if (!c || revision === undefined) return;
    try {
      const response = await this.request(c, `screenshot?revision=${revision}`);
      if (!response.headers.get("content-type")?.startsWith("image/png"))
        throw new Error("Server did not return a PNG screenshot.");
      if (
        response.headers.get("X-AW2-Match-ID") !== c.id ||
        response.headers.get("X-AW2-Revision") !== String(revision) ||
        response.headers.get("X-AW2-Frame") !== String(frame)
      )
        throw new Error(
          "Screenshot metadata does not match the displayed boundary.",
        );
      const blob = await response.blob();
      if (blob.size > 1024 * 1024 || blob.size < 8)
        throw new Error("Screenshot has an invalid size.");
      const signature = new Uint8Array(await blob.slice(0, 8).arrayBuffer());
      if (
        ![137, 80, 78, 71, 13, 10, 26, 10].every(
          (byte, i) => signature[i] === byte,
        )
      )
        throw new Error("Screenshot is not a PNG image.");
      if (
        this.connection !== c ||
        this.state.snapshot?.summary.revision !== revision
      )
        return;
      this.clearImage();
      this.update({
        image: URL.createObjectURL(blob),
        imageLabel: `Revision ${revision} · Frame ${frame}`,
        error: "",
      });
    } catch (error) {
      if (this.connection === c && !aborted(error))
        this.update({ error: message(error) });
    }
  };
}
