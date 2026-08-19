# n8n Workflows — BridgeGuard glue (T1002)

n8n is **glue, not logic** (Constitution III — modularity). It moves sensor data from
MQTT into the Data Collection Agent and routes the structured result. **No validation,
scoring, or decision logic lives in n8n** — all of that is in the Python service
(`src/agents/data_collection/`), which is independently testable and traced.

## `data_collection_ingestion.workflow.json`

The ingestion path:

```
MQTT Trigger (Mosquitto)         subscribe bridgeguard/+/sensors/#  (QoS 1)
        │   one message = one raw reading payload, forwarded as-is
        ▼
Batch Per Cycle                  time-window aggregate (~5s) -> one batch array
        │   window batching only; payload contents never inspected
        ▼
Invoke Data Collection Agent     POST {batch} -> $DCA_SERVICE_URL/run-cycle  (T1001)
        │   retries the invoke up to 3x on transport failure (Const. IV)
        ▼
Cycle OK?                        branch on the service's structured `ok` flag only
        ├── true  -> Cycle Accepted   (verdicts already persisted by the service)
        └── false -> Log Cycle Failure (ops alert; $json.error has the detail)
```

### What n8n does NOT do
- It does **not** parse, range-check, spike-detect, gap-fill, dedup, or judge liveness.
- It does **not** branch on any per-sensor verdict — only on the cycle-level `ok` flag.
- It does **not** write to Supabase. The Python service owns all persistence.

### Boundaries / deployment
- `$DCA_SERVICE_URL` points at the deployed T1001 entrypoint (`run_cycle` over HTTP).
- The clock enters the system at the service boundary, not here (determinism).

### [DB-DEP] / MQTT-live — deferred
This workflow is a reviewable **export + description**. It has **not** been run against
a live Mosquitto broker or Supabase instance (none available locally). Live verification
of the MQTT subscription, batching window, and end-to-end invoke is deferred until a
broker + Supabase exist — flagged here honestly, not faked.
