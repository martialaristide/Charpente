/** JSON-RPC 2.0 with `Content-Length` framing (the LSP/BSP wire format). No dependency on VS Code: unit-testable. */

export type JsonRpcMessage = {
  jsonrpc: "2.0";
  id?: number | string | null;
  method?: string;
  params?: unknown;
  result?: unknown;
  error?: { code: number; message: string; data?: unknown };
};

export const MAX_MESSAGE = 16 * 1024 * 1024;

export function encode(message: JsonRpcMessage): Buffer {
  const body = Buffer.from(JSON.stringify(message), "utf8");
  return Buffer.concat([Buffer.from(`Content-Length: ${body.length}\r\n\r\n`, "ascii"), body]);
}

/** Turns the bytes read from the server into complete messages, however the chunks are cut. */
export class FrameDecoder {
  private buffer: Buffer = Buffer.alloc(0);

  push(chunk: Buffer): JsonRpcMessage[] {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    const messages: JsonRpcMessage[] = [];
    for (;;) {
      const end = this.buffer.indexOf("\r\n\r\n");
      if (end < 0) {
        return messages;
      }
      const header = this.buffer.subarray(0, end).toString("ascii");
      const match = /^content-length:\s*(\d+)\s*$/im.exec(header);
      if (!match) {
        throw new Error(`missing Content-Length in header: ${JSON.stringify(header.slice(0, 80))}`);
      }
      const length = Number(match[1]);
      if (length > MAX_MESSAGE) {
        throw new Error(`message too large (${length} bytes)`);
      }
      const start = end + 4;
      if (this.buffer.length < start + length) {
        return messages;
      }
      const body = this.buffer.subarray(start, start + length).toString("utf8");
      this.buffer = this.buffer.subarray(start + length);
      messages.push(JSON.parse(body) as JsonRpcMessage);
    }
  }
}
