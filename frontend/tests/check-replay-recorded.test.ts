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

function tmpLayout(withRibbon: boolean): string {
  const file = path.join(os.tmpdir(), `layout-${Date.now()}-${Math.random()}.tsx`);
  fs.writeFileSync(
    file,
    withRibbon ? "<div>Not live readings from a bridge in Sindh.</div>" : "<div>nothing here</div>",
  );
  return file;
}

test("recorded:false with no honest note fails the build check", () => {
  const file = tmpFixture({ recorded: false });
  const layout = tmpLayout(true);
  const result = checkReplayRecorded(file, layout);
  assert.equal(result.ok, false);
  fs.unlinkSync(file);
  fs.unlinkSync(layout);
});

test("recorded:false with an honest mock note AND the ribbon present passes", () => {
  const file = tmpFixture({ recorded: false, note: "MOCK fixtures, not a real run." });
  const layout = tmpLayout(true);
  const result = checkReplayRecorded(file, layout);
  assert.equal(result.ok, true);
  fs.unlinkSync(file);
  fs.unlinkSync(layout);
});

test("recorded:false with an honest note but the ribbon missing still fails", () => {
  const file = tmpFixture({ recorded: false, note: "MOCK fixtures, not a real run." });
  const layout = tmpLayout(false);
  const result = checkReplayRecorded(file, layout);
  assert.equal(result.ok, false);
  fs.unlinkSync(file);
  fs.unlinkSync(layout);
});

test("recorded:true passes the build check regardless of the note or ribbon", () => {
  const file = tmpFixture({ recorded: true });
  const layout = tmpLayout(false);
  const result = checkReplayRecorded(file, layout);
  assert.equal(result.ok, true);
  fs.unlinkSync(file);
  fs.unlinkSync(layout);
});

test("a missing fixture file fails the build check", () => {
  const result = checkReplayRecorded(path.join(os.tmpdir(), "does-not-exist-12345.json"));
  assert.equal(result.ok, false);
});
