# Anonymous visitors and the computation queue

The web application runs without registration or sign-in. Scientific computation runs on the configured scientific checkout. Anonymous task ownership and the shared scientific results library are separate: a task receipt is browser-owned; the results library is shared. Public deployment remains pending.

## In the interface

The header displays online visitors, waiting tasks and running computations.
Open it to see this browser's recent tasks, queue positions, cancellation
controls and downloadable results. Refreshing a page does not delete a task.

Online visitors means browsers that sent a visible-page heartbeat within 90
seconds, not a verified number of people. Tabs in the same browser share one
anonymous cookie; private windows and separate browsers count separately. The
interface refreshes these counts every 15 seconds. Hidden pages do not renew
online presence. An unavailable service displays an unavailable state, not zero.

The server assigns an opaque, signed HttpOnly, SameSite=Strict cookie automatically. Explicit HTTPS proxy configuration also sets Secure. There is no
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

Service management files default to `<scientific root>/results/web-service/`, already excluded from Git. `EEG_QUEUE_DIRECTORY` or the service's `queueDirectory` option selects an explicit absolute directory. `queue.json` stores bounded task receipts, normalized requests, frozen keys,
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

## Maintenance

Maintenance state is saved with the queue. Startup with `EEG_MAINTENANCE=1` forces a pause; a saved pause survives startup without that setting. `SIGUSR2` pauses the running production host and `SIGUSR1` explicitly resumes it. There is no public maintenance write endpoint.

While paused, new uncached submissions and queue dispatch are blocked. Existing task retrieval, completed cache reads and cancellation remain available. Active work can finish and its receipt is reconciled. A pause during asynchronous request preparation or worker startup is checked before launching; a confirmed busy response restores the same queued receipt and order.

Health and status return `maintenance` and `drained`. Drained is true only while paused and with no active backend, execution permit, live worker or unresolved launch guard. Queued work remains intact. For a consistent backup, wait for drained and then stop the server: result/cache reads can still write receipts while paused. See [web operations](web-operations.md).

## IP logs and proxy access

Private access logs contain UTC time, the configured visitor IP and a hashed anonymous browser identifier. They are capped at 10 MiB per day and removed after seven days by hourly housekeeping while the server runs. Logs are not exposed through status or task endpoints.

Production binds to `127.0.0.1`. Without explicit public-origin/proxy configuration, Host, Origin and Fetch Metadata checks restrict API access to local requests; forwarding headers do not determine visitor IPs. A local installation therefore logs loopback addresses.

With `EEG_PUBLIC_ORIGIN` and explicit `EEG_TRUSTED_PROXIES`, a listed proxy must overwrite Host with the configured public host, `X-Forwarded-Proto` with `https`, and `X-Forwarded-For` with one actual client IP. Chains and untrusted forwarding headers are rejected. Cookies become Secure. Write-token and same-origin checks remain active. Cookie resets can bypass browser limits; IP limits do not establish a person's identity.

This policy has local tests. The actual proxy, public URL, access rules and record-sharing policy still need server acceptance. See [deployment preparation](server-deployment.md) and [dependency status](security.md).

## Verification

Run `npm run test:unit`, `npm run typecheck`, `npm run lint`, and `npm run build`
from `webapp/`. The queue tests use temporary directories and simulated workers, including pause/start races, restart order, persistence failure and unresolved workers. They do not run or modify FEM experiments. HTTP tests listen on loopback.

Run the numerical regression and real-data HTTP checks described in
[Contributing](../CONTRIBUTING.md) when changing worker execution or cache
handling. Recorded web checks are documented in [Web verification](verification.md).
