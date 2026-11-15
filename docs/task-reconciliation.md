# Recover interrupted task receipts

A stopped service can have a task receipt marked as running or interrupted even though its full result was saved before shutdown. `reconcile_service.py` checks that completed cache before changing the receipt. It never launches a calculation, retries a task or edits scientific results, projects, electrode names or browser-session credentials.

Put the service in maintenance mode, drain it and stop the service process first. Keep the original queue and session secret together. A legacy queue without persisted maintenance can be inspected, but cannot be changed by this tool; start, pause, drain and stop the existing application to persist that state first.

Preview a plan under the scientific root’s `artifacts/` directory:

```bash
python scripts/reconcile_service.py \
  --root /absolute/path/scientific-root \
  --plan /absolute/path/scientific-root/artifacts/reconciliation/preview.json
```

Use `--queue-directory` if the queue is outside the default `results/web-service`. Use `--python` when a separately configured qualified scientific interpreter is required. The tool retains the application’s managed-runtime selection rules.

Review `changes`, `retained` and `blocked_reasons` in the saved plan. Apply that exact plan with the queue SHA-256 printed by the preview:

```bash
python scripts/reconcile_service.py \
  --root /absolute/path/scientific-root \
  --plan /absolute/path/scientific-root/artifacts/reconciliation/preview.json \
  --execute --expected-queue-sha256 THE_PREVIEW_QUEUE_SHA256
```

Apply rechecks the original queue bytes, current scientific request and identity, complete production cache validation, tool files and runtime. A live service or worker, an uncertain worker start, changed input, missing cache or failed checksum blocks recovery. Make a new preview after resolving the cause.

Only interrupted running receipts with an exact validated completed result can become completed; the original layout-search protocol can also recover its valid `no_layout` result. Cancelled or cancelling tasks remain cancelled or cancelling. Queue order, owners, scientific requests and electrode annotation references remain intact. Before an actual change, the tool saves the exact original queue bytes beside the plan, then replaces the queue atomically while holding both service acquisition and native writer locks. A preview with no changes does not rewrite the queue.
