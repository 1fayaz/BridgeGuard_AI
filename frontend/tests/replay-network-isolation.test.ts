import { test } from "node:test";
import assert from "node:assert/strict";
import { loadReplayTimeline } from "../lib/demo-contract.ts";

// Safety rule: replay mode must make zero backend calls — only the static fixture file.
// specs/005-demo-mode-and-approval/spec.md, "REPLAY mode: ... no backend calls, no login."
test("loadReplayTimeline calls fetch exactly once, only for the static replay file", async () => {
  const calls: string[] = [];
  const fakeFetch = (async (url: string) => {
    calls.push(url);
    return {
      ok: true,
      json: async () => ({ recorded: false, generated_at: "", bridge_id: "", cycle_id: "", is_demo: true, timeline: [] }),
    };
  }) as typeof fetch;

  await loadReplayTimeline(fakeFetch);

  assert.equal(calls.length, 1, "replay must make exactly one call");
  assert.equal(calls[0], "/replay/demo-run.json", "replay must never call anything but the static fixture");
  assert.ok(!calls[0].includes("/v1/"), "replay must never reach a backend endpoint");
});
