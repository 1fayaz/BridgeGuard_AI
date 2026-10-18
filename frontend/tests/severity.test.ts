import { test } from "node:test";
import assert from "node:assert/strict";
import { SEVERITY_CONFIG } from "../lib/data.ts";

// Safety rule: an Unknown/offline state must never be styled as safe.
// specs/005-demo-mode-and-approval/spec.md §4 FR-4.2.
test("UNKNOWN never uses the safe colour or safe label", () => {
  const unknown = SEVERITY_CONFIG.UNKNOWN;
  const safe = SEVERITY_CONFIG.SAFE;
  assert.notEqual(unknown.bar, safe.bar);
  assert.notEqual(unknown.bgHex, safe.bgHex);
  assert.notEqual(unknown.label.toLowerCase(), "safe");
  // The design's green is #097F37 specifically — UNKNOWN must never render it, under any name.
  assert.notEqual(unknown.bar.toUpperCase(), "#097F37");
});

test("every severity has a distinct, non-empty colour", () => {
  const bars = Object.values(SEVERITY_CONFIG).map((c) => c.bar);
  assert.equal(new Set(bars).size, bars.length, "severities must not share a colour");
  bars.forEach((b) => assert.ok(b.length > 0));
});
