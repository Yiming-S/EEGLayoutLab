# Anonymous visitors and the computation queue

This page describes the queue of the legacy Node host (`npm start`), which hosted deployments keep at the tag `node-host-freeze` until phase 4 of [design 0001](design/0001-local-first-architecture.md). The application's host is now the local Python service, `eeglayoutlab serve`, for one user: its queue belongs to the workspace (`<workspace>/.eeglayoutlab/queue.json`) and has no visitors, browser cookies, rate limits or library visibility ([not carried over](design/0001-phase-2-plan.md#not-carried-over)); [CONTRIBUTING](../CONTRIBUTING.md#the-local-service) describes it.

The Node host runs without registration or sign-in. Scientific computation runs on the configured scientific checkout. A task receipt is owned by the browser that submitted it. Finished records are listed in the shared result library to every visitor; the operator can remove a record from it (see [Shared library visibility](#shared-library-visibility)).

## In the interface

The header's **Tasks / Queue** badge shows the waiting tasks and running
computations. Open it to see the recent tasks, queue positions, cancellation
controls and downloadable results. Refreshing a page does not delete a task.

The interface reads these counts from `GET /api/community/status` every 15
seconds, when the page becomes visible, and at once when a request of the page
finds the session ended or no service. It shows no visitor count and sends no
heartbeat, on either host: the Node host's `online_visitors` and its
`POST /api/community/heartbeat` are no longer used, so that host's visitor count
and visit log do not see the current interface. An unavailable service displays
an unavailable state, not zero. A tab whose service has ended (`eeglayoutlab
serve` takes a new port and new secrets on every start) shows how to open the
application again.

The server assigns an opaque, signed HttpOnly, SameSite=Strict cookie automatically. It lasts 30 days and each page visit renews it. Explicit HTTPS proxy configuration also sets Secure. There is no
account, email or password. Clearing that cookie removes the browser's ability
to manage its prior task receipts; the records themselves stay in the shared
library. Only the submitting
browser or another browser that submits the same exact experiment can access
that shared task's receipt.

## Shared library visibility

Every finished record is listed in the shared library to every visitor: the
official experiment records and the records produced by visitors' computations
(radius designs, coordinate evaluations and electrode edits), including the
names visitors gave their coordinate files. Signal experiments stay limited to
the submitting browser's receipts, robustness studies to the browser that
created them, and projects to their credentials.

The browsers that submitted or looked up a record are recorded as its owners
(hashed browser identifiers in `<queue directory>/library/records/<id>.json`;
back them up with the rest of the queue directory). A browser that cancelled or
left a shared task before it finished does not own the result.

The operator can remove a visitor record. A removed record disappears from every
list, its links (`/library?record=<id>`, comparison links and bundles) stop
working for everyone except its owners, and its owners see the removal and its
reason. The record identifier is in the record's link. Run the tool on the
server from `webapp/`; the running server rereads
`<queue directory>/library/moderation.json` on its next list request:

```sh
npm run library:moderate -- --queue-directory /srv/eeg/queue remove <id> --reason "text shown to the owner"
npm run library:moderate -- --queue-directory /srv/eeg/queue restore <id>
npm run library:moderate -- --queue-directory /srv/eeg/queue list
```

`EEG_LIBRARY_SCOPE=owner` is an optional stricter mode: a visitor's records are
listed only to its owners until an owner publishes them (`POST
/api/local-compute/library/<id>/visibility`; the current interface no longer has
the record page's publication control, so its records stay unlisted to others),
and with `EEG_LIBRARY_REVIEW=1` (the default in that mode) a publication is
listed to others only after `approve <id>`; `list --pending` shows the waiting
ones. Records made before owners were recorded have no owner and are listed to
no one in that mode. Unlisted records still open from their links.

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

Queue limits are 50 unfinished unique tasks globally, 3 unfinished subscribed
tasks per browser and 6 per client network. Submission and lookup limits are 20
requests per browser and 100 per client network per minute. A client network is
an IPv4 address or an IPv6 /64, the block one subscriber usually controls; the
queue stores only a keyed hash of it. Network limits exist because a fresh cookie
costs nothing. Cached reads still count toward request-rate limits but do not
consume queue capacity.

Other per-network shares: 15 robustness studies, 30 research projects and 60 new
electrode-name sets per hour. Study drafts that were never started are deleted
after 7 days, and projects that were never edited and hold no entries after 30
days, so abandoned drafts do not hold the global limits (100 studies, 1000
projects). Saved signal results are about 8 MB; at most two are serialized at a
time, and the two most recently verified files are kept in memory. Worker timeouts start on execution,
not while waiting. Existing service timeouts and thread limits are unchanged.

Cancelling a waiting task is immediate. Cancelling a running task waits for
process exit before dispatching the next task. Leaving a shared task removes
only the requesting browser; the worker continues while another subscriber
remains. New submissions do not join a task that is already stopping.

## Storage and restart behavior

Service management files default to `<scientific root>/results/web-service/`, already excluded from Git. `EEG_QUEUE_DIRECTORY` or the service's `queueDirectory` option selects an explicit absolute directory. `queue.json` stores bounded task receipts, normalized requests, frozen keys,
sequence numbers and hashed browser ownership. Numerical results are kept in
the existing `results/v2/*_jobs` caches, not duplicated in the queue snapshot.
Terminal receipts are kept in two pools. Receipts of computed tasks, which are
bounded by compute throughput, keep the newest 1000. Receipts created by opening
an existing result cost nothing to request, so they keep the newest 300, at most
40 per client network: a script cannot push other visitors' results out, and a
visitor who loses such a receipt gets it back by opening the result again. Older
scientific results can still be obtained by submitting their exact configuration
or opening the result library. Queued and unresolved worker records are never
evicted.

Errors from the file system or from server code are answered with status 500
and a generic message; the full error goes to the service log, and absolute
server paths are removed from every error and job message. A failed queue write
(for example a full disk) stops new work and is retried on each scheduling tick,
so freeing space resumes service. A shutdown that arrives while a worker launch
is still in flight puts that task back in the queue; a launch that failed with an
unknown outcome keeps its recovery guard for the operator.

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

With `EEG_PUBLIC_ORIGIN` and explicit `EEG_TRUSTED_PROXIES`, a listed proxy must overwrite Host with the configured public host, `X-Forwarded-Proto` with `https`, and `X-Forwarded-For` with one actual client IP. Chains and untrusted forwarding headers are rejected. Cookies become Secure. Write-token and same-origin checks remain active. Cookie resets can bypass browser limits; IP limits do not establish a person's identity. On a public host, a loopback request that carries any forwarding header (`X-Forwarded-*`, `Forwarded`, `Via`) is rejected, so a proxy that rewrites Host to `localhost` cannot make every visitor share 127.0.0.1. Do not enable Caddy's `trusted_proxies`: it turns `X-Forwarded-For` into a list, which this server rejects. Node closes requests whose headers take longer than 15 s or whose body takes longer than 30 s.

This policy has local tests. The actual proxy, public URL, access rules and record-sharing policy still need server acceptance. See [deployment preparation](server-deployment.md) and [dependency status](security.md).

## Verification

Run `npm run test:unit`, `npm run typecheck`, `npm run lint`, and `npm run build`
from `webapp/`. The queue tests use temporary directories and simulated workers, including pause/start races, restart order, persistence failure and unresolved workers. They do not run or modify FEM experiments. HTTP tests listen on loopback.

Run the numerical regression and real-data HTTP checks described in
[Contributing](../CONTRIBUTING.md) when changing worker execution or cache
handling.
