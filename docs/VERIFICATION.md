# Review studio release candidate

## Executed locally

Python 3.13 on Windows; unit tests cover existing account/configuration safety and hidden Tk logging plus new plan order/duplicates/skips, exact destination, stale/mutated plan refusal, private copies, 205-item chunking, ambiguous timeout stop, selection/schema rejection, current API endpoints, rate/quota handling, incomplete pagination and PKCE construction.

Real Chromium interactions on port 4631 exercise review and simulation with synthetic data. PNG captures are actual running UI, not generated mockups. The local synthetic fixture represents no songs or accounts observed from Spotify.

## Not verified

A real Spotify app/client ID, allowlisted account and user-assisted browser consent are needed for live export verification. Live write execution, cross-account availability, real quota behavior and public distribution are unverified. The studio does not perform live writes. The legacy Tk transfer remains incomplete and is explicitly discouraged for production imports/erase.

## Reconciliation

Write timeouts may occur after a server committed an item batch. Reports mark `needs_reconciliation` and stop. `added` counts only acknowledged batches; it is not a statement that unacknowledged items were absent. Inspect the returned playlist ID before any retry. Creation-timeout IDs may be unavailable; inspect the destination account for the requested playlist name. Automatic crash recovery and resume are future work.

## Security boundaries

Studio accepts same-origin POSTs and exact loopback Host, caps request bodies at 2 MB, uses text nodes for imported names and a restrictive CSP. PKCE binds state and loopback callback, verifies exact account ID, requests only playlist read scopes, never persists tokens and suppresses callback URL logs. Private export files are user-owned sensitive content and should stay out of version control.
