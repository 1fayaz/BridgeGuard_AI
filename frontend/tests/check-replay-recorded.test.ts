import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { checkReplayRecorded } from "../scripts/check-replay-recorded.js";

function tmpFixture(content: unknown): string {
  const file = path.join(os.tmpdir(), `demo-run-${Date.now()}-${Math.random()}.json`);
  fs.writeFileSync(file, JSON.stringify(content));
  return file;
}

test("recorded:false fails the build check", () => {
  const file = tmpFixture({ recorded: false });
  const result = checkReplayRecorded(file);
  assert.equal(result.ok, false);
  fs.unlinkSync(file);
});

test("recorded:true passes the build check", () => {
  const file = tmpFixture({ recorded: true });
  const result = checkReplayRecorded(file);
  assert.equal(result.ok, true);
  fs.unlinkSync(file);
});

test("a missing fixture file fails the build check", () => {
  const result = checkReplayRecorded(path.join(os.tmpdir(), "does-not-exist-12345.json"));
  assert.equal(result.ok, false);
});
