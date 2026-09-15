# Anonymous visitors and the computation queue

The current web source runs without registration or sign-in. Scientific
computation remains on the host computer. This update does not publish a public
website or change the scientific model, cache identities, or numerical scores.

## In the interface

The header displays online visitors, waiting tasks and running computations.
Open it to see this browser's recent tasks, queue positions, cancellation
controls and downloadable results. Refreshing a page does not delete a task.

Online visitors means browsers that sent a visible-page heartbeat within 90
seconds, not a verified number of people. Tabs in the same browser share one
anonymous cookie; private windows and separate browsers count separately. The
interface refreshes these counts every 15 seconds. Hidden pages do not renew
online presence. An unavailable service displays an unavailable state, not zero.

The server assigns an opaque, signed HttpOnly cookie automatically. There is no
account, email or password. Clearing that cookie removes the browser's ability
to manage its prior task receipts. Saved scientific records remain in the
existing result library. Only the submitting browser or another browser that
submits the same exact experiment can access that shared task's receipt.

## Scheduling and reuse

All four services share one FIFO execution slot: region design, coordinate
evaluation, electrode editing, and source reception (both signal protocols).

1. Validate and normalize the request and compute its existing scientific key.
2. Return a verified completed cache immediately, without occupying the slot.
3. If the identical key is queued or running, subscribe to that task.
4. Otherwise save a new request to disk and assign a monotonically increasing
   sequence. Valid requests are accepted serially; execution follows this order.
5. Revalidate the frozen key before dispatch. A changed model, code, parent
   layout or runtime requires a new submission rather than a silent substitution.
6. Release the slot only after the worker has closed and its service has finished
   result validation and persistence.

Queue limits are 50 unfinished unique tasks globally and 3 unfinished subscribed
tasks per browser. Submission and lookup limits are 20 requests per browser and
100 per connecting IP per minute. Cached reads still count toward request-rate
limits but do not consume queue capacity. Worker timeouts start on execution,
not while waiting. Existing service timeouts and thread limits are unchanged.

Cancelling a waiting task is immediate. Cancelling a running task waits for
process exit before dispatching the next task. Leaving a shared task removes
only the requesting browser; the worker continues while another subscriber
remains. New submissions do not join a task that is already stopping.

## Storage and restart behavior

Service management files live in `results/web-service/`, already excluded from
Git. `queue.json` stores bounded task receipts, normalized requests, frozen keys,
sequence numbers and hashed browser ownership. Numerical results are kept in
the existing `results/v2/*_jobs` caches, not duplicated in the queue snapshot.
The newest 500 terminal receipts are retained; older scientific results can
still be obtained by submitting their exact configuration or opening the
result library. Queued and unresolved worker records are never evicted.

Queue updates use a temporary file, fsync, atomic rename and directory fsync.
One server owns the directory using an exclusive lock. Do not run independent
servers against the same state directory. This is a single-host queue, not a
distributed worker system.

After restart, queued tasks retain their order. A running numerical computation
does not have a resumable checkpoint: its receipt reports interruption and can
be resubmitted. A completed, validated scientific cache is reused on resubmission.
Any still-live recorded worker PID blocks new dispatch until that PID exits,
including across repeated restarts. A crash between launch intent and PID
recording pauses dispatch for operator inspection instead of assuming that no
worker exists.

If `acquiring.lock` remains after a crash, or a task has `starting: true` without
a recorded PID, stop all app servers and inspect the process list for the four
Python worker entry points. Preserve the service directory for diagnosis. Only
after confirming those workers are stopped may an operator remove the stale
acquisition guard or clear that task's unresolved `starting` marker. Do not
delete the whole queue or its session secret to work around a busy service.

## IP logs and public deployment boundary

Private access logs contain UTC time, the connecting IP and a hashed anonymous
browser identifier. They are capped at 10 MiB per day and removed after seven
days by hourly housekeeping while the server runs. Logs are not exposed through
the status or task endpoints. No third-party analytics is introduced.

The local service still binds to `127.0.0.1`; Host, Origin, Fetch Metadata and
write-token checks remain enabled. It deliberately ignores `X-Forwarded-For`.
On this local installation the recorded connecting IP is loopback, not a remote
visitor's public IP. Public deployment requires a separately configured HTTPS
origin, trusted proxy boundary and secure-cookie settings. Cookie resets can
bypass per-browser limits; IP limits are an additional control, not proof of
identity. The pre-existing dependency audit and deployment review remain a
separate requirement. See [security](security.md).

## Verification

Run `npm run test:unit`, `npm run typecheck`, `npm run lint`, and `npm run build`
from `webapp/`. The queue tests use temporary directories and simulated workers;
they do not run or modify the FEM experiments. HTTP tests listen on loopback.

Existing numerical regression tests, saved record values and the scientific
cache format remain unchanged. The desktop DMG is an archived build and does
not contain the later web-source queue changes.
