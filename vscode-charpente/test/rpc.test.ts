import assert from "node:assert/strict";
import { test } from "node:test";
import { FrameDecoder, encode } from "../src/rpc";

test("encode counts bytes, not characters", () => {
  const data = encode({ jsonrpc: "2.0", id: 1, method: "x", params: { text: "héllo ✓" } });
  const text = data.toString("utf8");
  const [header, body] = text.split("\r\n\r\n");
  assert.equal(Number(header.split(":")[1]), Buffer.byteLength(body, "utf8"));
});

test("decoder reads messages however the chunks are cut", () => {
  const a = encode({ jsonrpc: "2.0", id: 1, result: "é" });
  const b = encode({ jsonrpc: "2.0", method: "note", params: { n: 2 } });
  const all = Buffer.concat([a, b]);
  for (let cut = 1; cut < all.length; cut += 7) {
    const decoder = new FrameDecoder();
    const got = [...decoder.push(all.subarray(0, cut)), ...decoder.push(all.subarray(cut))];
    assert.equal(got.length, 2, `cut at ${cut}`);
    assert.equal(got[0].result, "é");
    assert.equal(got[1].method, "note");
  }
});

test("decoder ignores extra headers and rejects a missing length", () => {
  const body = '{"jsonrpc":"2.0","id":5,"result":null}';
  const ok = Buffer.from(`Content-Type: application/vscode-jsonrpc; charset=utf-8\r\ncontent-length: ${body.length}\r\n\r\n${body}`);
  assert.equal(new FrameDecoder().push(ok)[0].id, 5);
  assert.throws(() => new FrameDecoder().push(Buffer.from("X-Other: 1\r\n\r\n{}")), /Content-Length/);
  assert.throws(() => new FrameDecoder().push(Buffer.from("Content-Length: 999999999\r\n\r\n")), /too large/);
});

test("decoder waits for a complete body", () => {
  const decoder = new FrameDecoder();
  const data = encode({ jsonrpc: "2.0", id: 1, result: 1 });
  assert.deepEqual(decoder.push(data.subarray(0, data.length - 1)), []);
  assert.equal(decoder.push(data.subarray(data.length - 1)).length, 1);
});
