#!/usr/bin/env node
// Fails the production build if the replay fixture is still a mock ("recorded": false).
// Only the backend's record script (scripts/demo/generate_replay_fixtures.py --mode record)
// is allowed to write frontend/public/replay/demo-run.json — see specs/005-demo-mode-and-approval/
// spec.md, "Files this feature may write". This check is what makes that rule enforced, not just
// documented.
const fs = require("fs");
const path = require("path");

const FIXTURE_PATH = path.join(__dirname, "..", "public", "replay", "demo-run.json");

function checkReplayRecorded(fixturePath) {
  if (!fs.existsSync(fixturePath)) {
    return { ok: false, reason: `missing fixture file: ${fixturePath}` };
  }
  const data = JSON.parse(fs.readFileSync(fixturePath, "utf-8"));
  if (data.recorded !== true) {
    return {
      ok: false,
      reason:
        `demo-run.json has "recorded": ${JSON.stringify(data.recorded)} — a mock fixture ` +
        `cannot ship to production. Run scripts/demo/generate_replay_fixtures.py --mode record first.`,
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
  console.log("✓ Replay fixture is a real recorded run.");
}

module.exports = { checkReplayRecorded };
