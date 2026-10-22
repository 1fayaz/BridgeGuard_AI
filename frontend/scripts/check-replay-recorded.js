#!/usr/bin/env node
// Fails the production build if the replay fixture is a silent/unlabelled mock. A mock fixture
// ("recorded": false) may still ship - but only when it is honestly labelled as a mock AND the
// site-wide ribbon disclosing "not live" is still present in the app shell. Remove either one and
// the build fails. This is deliberately NOT a rubber stamp to set "recorded": true on anything
// that isn't a real recorded run - see scripts/demo/generate_replay_fixtures.py --mode record.
const fs = require("fs");
const path = require("path");

const FIXTURE_PATH = path.join(__dirname, "..", "public", "replay", "demo-run.json");
const LAYOUT_PATH = path.join(__dirname, "..", "app", "layout.tsx");
const RIBBON_TEXT = "Not live readings from a bridge in Sindh";

function checkReplayRecorded(fixturePath, layoutPath = LAYOUT_PATH) {
  if (!fs.existsSync(fixturePath)) {
    return { ok: false, reason: `missing fixture file: ${fixturePath}` };
  }
  const data = JSON.parse(fs.readFileSync(fixturePath, "utf-8"));

  if (data.recorded === true) {
    return { ok: true };
  }

  const hasHonestNote = typeof data.note === "string" && /mock/i.test(data.note);
  if (!hasHonestNote) {
    return {
      ok: false,
      reason:
        `demo-run.json has "recorded": ${JSON.stringify(data.recorded)} and no honest mock ` +
        `note ("note" must mention "mock") — cannot ship. Run ` +
        `scripts/demo/generate_replay_fixtures.py --mode record for a real run, or restore the note.`,
    };
  }

  if (!fs.existsSync(layoutPath)) {
    return { ok: false, reason: `cannot verify the replay banner — missing layout file: ${layoutPath}` };
  }
  const layoutSrc = fs.readFileSync(layoutPath, "utf-8");
  if (!layoutSrc.includes(RIBBON_TEXT)) {
    return {
      ok: false,
      reason:
        `demo-run.json is an honestly-labelled mock, but the site-wide "not live" ribbon ` +
        `(expected text: ${JSON.stringify(RIBBON_TEXT)}) is missing from ${layoutPath} — ` +
        `a mock fixture cannot ship without it visible on every page.`,
    };
  }

  return { ok: true };
}

if (require.main === module) {
  const result = checkReplayRecorded(FIXTURE_PATH);
  if (!result.ok) {
    console.error(`\n✗ Build check failed: ${result.reason}\n`);
    process.exit(1);
  }
  console.log("✓ Replay fixture is a real recorded run, or an honestly-labelled mock with the ribbon in place.");
}

module.exports = { checkReplayRecorded };
