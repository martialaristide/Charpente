import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { after, before, test } from "node:test";
import { ServerClient, ServerError, pathToUri } from "../src/client";

const python = process.env.CHARPENTE_PYTHON ?? (process.platform === "win32" ? "python" : "python3");
const haveCompiler = ["g++", "clang++"].some((c) => {
  try {
    execFileSync(c, ["--version"], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
});

const WORKSPACE = `from charpente import *

with Workspace("demo", version="1.0.0") as ws:
    with Target("lib") as lib:
        lib.kind(Kind.STATIC_LIBRARY)
        lib.standard("c++17")
        lib.sources(["src/lib.cpp"])

    with Target("app") as app:
        app.kind(Kind.EXECUTABLE)
        app.standard("c++17")
        app.sources(["src/main.cpp"])
        app.uses("lib")
`;

let root: string;
const env = { ...process.env, CHARPENTE_TRUST_ALL: "1", PYTHONIOENCODING: "utf-8" };

before(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), "vscode-charpente-"));
  fs.mkdirSync(path.join(root, "src"));
  fs.writeFileSync(path.join(root, "demo.charpente"), WORKSPACE);
  fs.writeFileSync(path.join(root, "src", "lib.cpp"), "int value() { return 3; }\n");
  fs.writeFileSync(path.join(root, "src", "main.cpp"), "int value();\nint main() { return value() - 3; }\n");
});

after(() => {
  fs.rmSync(root, { recursive: true, force: true });
});

test("the client talks BSP to a real charpente server", async () => {
  const client = new ServerClient([python, "-m", "charpente"], root, env);
  const notes: string[] = [];
  client.on("notification", (n: { method: string }) => notes.push(n.method));
  const info = await client.start();
  try {
    assert.equal(info.displayName, "charpente");
    assert.equal(info.bspVersion, "2.1.0");
    assert.ok(client.running);

    const workspace = await client.request("charpente/workspace");
    assert.equal(workspace.name, "demo");

    const targets = (await client.request("workspace/buildTargets")).targets;
    assert.deepEqual(targets.map((t: any) => t.displayName).sort(), ["app", "lib"]);

    const graph = await client.request("charpente/graph");
    assert.ok(graph.order.indexOf("lib") < graph.order.indexOf("app"));

    await assert.rejects(client.request("no/such/method"), (e: unknown) => e instanceof ServerError && e.code === -32601);
    await assert.rejects(client.request("charpente/explain", { code: "CH999999" }), ServerError);

    const commands = (await client.request("charpente/compileCommands")).entries;
    assert.equal(commands.length, 2);
    assert.ok(commands.every((e: any) => path.isAbsolute(e.file) && Array.isArray(e.arguments) && e.arguments.includes("-c")));

    if (haveCompiler) {
      const app = targets.find((t: any) => t.displayName === "app");
      const result = await client.request("buildTarget/compile", { targets: [app.id], arguments: ["--config", "Debug"], originId: "t" });
      assert.equal(result.statusCode, 1);
      assert.ok(notes.includes("build/taskStart") && notes.includes("build/taskFinish"));
    }
  } finally {
    await client.stop();
  }
  assert.equal(client.running, false);
  await assert.rejects(client.request("charpente/ping"), /not running/);
});

test("a missing charpente command is reported, not hung", async () => {
  const client = new ServerClient(["definitely-not-a-real-program-xyz"], root, env);
  await assert.rejects(client.start(), /cannot start/);
});

test("a workspace that does not load is an error with the message of Charpente", async () => {
  const empty = fs.mkdtempSync(path.join(os.tmpdir(), "vscode-charpente-empty-"));
  const client = new ServerClient([python, "-m", "charpente"], empty, env);
  try {
    await client.start();
    await assert.rejects(
      client.request("workspace/buildTargets"),
      (e: unknown) => e instanceof ServerError && e.code === -32001 && /CH\d{4}/.test(e.message),
    );
  } finally {
    await client.stop();
    fs.rmSync(empty, { recursive: true, force: true });
  }
});

test("the root is sent as a file URI", () => {
  assert.match(pathToUri(root), /^file:\/\/\//);
});
