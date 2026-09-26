/** A client of `charpente serve --stdio`: starts the server, sends requests, delivers notifications. */
import { ChildProcess, spawn } from "node:child_process";
import { EventEmitter } from "node:events";
import { FrameDecoder, JsonRpcMessage, encode } from "./rpc";

export class ServerError extends Error {
  constructor(
    message: string,
    readonly code: number,
    readonly data?: unknown,
  ) {
    super(message);
  }
}

export interface Notification {
  method: string;
  params: any;
}

type Pending = { resolve: (value: any) => void; reject: (error: Error) => void };

/**
 * Events: `notification` (Notification), `stderr` (string), `exit` (code number | null).
 * Nothing is sent before `start()` resolves; after the server exits every pending request is rejected.
 */
export class ServerClient extends EventEmitter {
  private child?: ChildProcess;
  private readonly decoder = new FrameDecoder();
  private readonly pending = new Map<number, Pending>();
  private nextId = 1;
  private closed = false;
  info: any;

  constructor(
    private readonly command: string[],
    private readonly root: string,
    private readonly env: NodeJS.ProcessEnv = process.env,
  ) {
    super();
  }

  get running(): boolean {
    return this.child !== undefined && !this.closed;
  }

  async start(): Promise<any> {
    const [program, ...args] = this.command;
    if (!program) {
      throw new Error("the charpente.command setting is empty");
    }
    const child = spawn(program, [...args, "serve", "--stdio", "--root", this.root], {
      cwd: this.root,
      env: this.env,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    this.child = child;
    const started = new Promise<void>((resolve, reject) => {
      child.once("spawn", () => resolve());
      child.once("error", (error) => reject(new Error(`cannot start ${program}: ${error.message}`)));
    });
    child.stdout!.on("data", (chunk: Buffer) => this.onData(chunk));
    child.stderr!.on("data", (chunk: Buffer) => this.emit("stderr", chunk.toString("utf8")));
    child.on("error", (error) => this.failAll(error));
    child.on("close", (code) => {
      this.closed = true;
      this.failAll(new Error(`the Charpente server exited (code ${code})`));
      this.emit("exit", code);
    });
    await started;
    this.info = await this.request("build/initialize", {
      displayName: "vscode-charpente",
      version: "0.12.0",
      bspVersion: "2.1.0",
      rootUri: pathToUri(this.root),
      capabilities: { languageIds: ["c", "cpp"] },
    });
    this.notify("build/initialized", {});
    return this.info;
  }

  request<T = any>(method: string, params: unknown = {}): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      if (!this.running) {
        reject(new Error("the Charpente server is not running"));
        return;
      }
      const id = this.nextId++;
      this.pending.set(id, { resolve, reject });
      this.write({ jsonrpc: "2.0", id, method, params });
    });
  }

  notify(method: string, params: unknown = {}): void {
    if (this.running) {
      this.write({ jsonrpc: "2.0", method, params });
    }
  }

  /** Ask the server to finish (BSP shutdown/exit), then make sure the process is gone. */
  async stop(timeoutMs = 5000): Promise<void> {
    const child = this.child;
    if (!child || this.closed) {
      return;
    }
    const done = new Promise<void>((resolve) => child.once("close", () => resolve()));
    try {
      await Promise.race([this.request("build/shutdown"), new Promise((r) => setTimeout(r, timeoutMs))]);
    } catch {
      // the server may already be gone: fine
    }
    this.notify("build/exit");
    const timer = setTimeout(() => child.kill(), timeoutMs);
    await done;
    clearTimeout(timer);
  }

  private write(message: JsonRpcMessage): void {
    this.child!.stdin!.write(encode(message));
  }

  private onData(chunk: Buffer): void {
    let messages: JsonRpcMessage[];
    try {
      messages = this.decoder.push(chunk);
    } catch (error) {
      this.emit("stderr", `protocol error: ${(error as Error).message}\n`);
      this.child?.kill();
      return;
    }
    for (const message of messages) {
      if (message.method !== undefined && message.id === undefined) {
        this.emit("notification", { method: message.method, params: message.params } as Notification);
      } else if (typeof message.id === "number") {
        const waiting = this.pending.get(message.id);
        if (!waiting) {
          continue;
        }
        this.pending.delete(message.id);
        if (message.error) {
          waiting.reject(new ServerError(message.error.message, message.error.code, message.error.data));
        } else {
          waiting.resolve(message.result);
        }
      }
    }
  }

  private failAll(error: Error): void {
    for (const waiting of this.pending.values()) {
      waiting.reject(error);
    }
    this.pending.clear();
  }
}

export function pathToUri(path: string): string {
  const normalised = path.replace(/\\/g, "/");
  const prefixed = normalised.startsWith("/") ? normalised : `/${normalised}`;
  return "file://" + prefixed.split("/").map((part) => encodeURIComponent(part).replace(/%3A/g, ":")).join("/");
}

export function uriToPath(uri: string): string {
  const url = new URL(uri);
  if (url.protocol !== "file:") {
    throw new Error(`not a file: URI: ${uri}`);
  }
  let path = decodeURIComponent(url.pathname);
  if (/^\/[A-Za-z]:/.test(path)) {
    path = path.slice(1);
  }
  return path;
}
