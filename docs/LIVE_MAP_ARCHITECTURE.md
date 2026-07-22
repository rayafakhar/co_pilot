# Live map architecture

Northstar's live network map is a visualization of the deterministic schedule. It is
not a tracking system and does not consume GPS, ADS-B, radar, or airline operational
data. Aircraft positions are derived from effective schedule times and the persistent
simulation clock.

~~~mermaid
flowchart TD
    CLOCK[SimulationClock] --> ENDPOINT[Django map endpoint]
    ENDPOINT -->|15-second polling| STATE[Client state reconciler]
    STATE --> TURF[Turf route and interpolation]
    TURF --> MAP[MapLibre GeoJSON sources]
~~~

## 1. Django remains authoritative

Django owns the schedule, effective timestamps, lifecycle state, public flight
identity, and the single simulation instant used for each response. The browser never
promotes its device clock into operational truth and never derives a flight's status
independently. The map endpoint projects only fields needed by the visualization.

## 2. Wall time and simulation time

Wall time is the real aware UTC time at which code runs. Simulation time starts at a
stored schedule anchor and advances from the stored wall-clock start by the configured
speed multiplier. Pausing freezes an explicit simulation instant. Resume and speed
changes preserve continuity, while reset returns to the original schedule anchor.

The singleton clock survives process restarts. A missing clock produces a labelled
wall-time fallback for an empty or legacy database; an invalid stored clock produces a
no-store 503 response rather than silently inventing state.

## 3. Polling and interpolation

The client polls `/network-map/data/` every 15 seconds with no-store fetches. Each
request has an abort controller and increasing sequence number, so a superseded or
older response cannot overwrite newer state. A valid response becomes a new
authoritative snapshot.

Between snapshots, the browser advances the response's simulation timestamp by the
reported speed and interpolates only within the effective departure/arrival window.
The visual animation is corrected gently toward each new authoritative progress
value. It does not change persisted data or server lifecycle state.

## 4. Why MapLibre

MapLibre GL JS provides an open-source WebGL renderer with GeoJSON sources, data-driven
styles, interaction, accessibility-compatible controls, and a clear separation between
the base raster tiles and operational overlays. The map instance, five GeoJSON sources,
and their layers are installed once and updated in place.

The tile URL and attribution come from public Django settings passed through a safe
JSON configuration block. Tile failure is treated separately from flight-data failure,
so operational overlays can still be understood when the basemap is unavailable.

## 5. Why Turf

Only modular Turf packages are bundled. Turf builds great-circle geometry, measures
route length, finds a point along a route, and calculates the aircraft bearing. This
keeps route math explicit and testable without importing the full Turf package.

## 6. Diversion geometry

Normal flights use the planned arrival airport. A diverted flight uses its diversion
airport as `result_destination`, and the route geometry, progress, bearing, label, and
detail panel all follow that resulting airport. The planned destination remains in the
payload for an honest schedule-versus-result comparison.

## 7. Antimeridian handling

Turf great-circle output may become a `MultiLineString` when a route crosses the
international date line. The client samples distance across every segment without
drawing a false line around the other side of the globe. The server computes a narrow
longitude interval that may extend beyond 180 degrees, allowing MapLibre to fit the
actual network instead of nearly the whole world.

## 8. Stale and malformed responses

Payload schema version 1 is validated before reconciliation. Records with missing or
invalid public identity, timing, or coordinates are skipped and counted. If no prior
valid state exists, an invalid response is a visible error. During a short later
outage, the last valid state stays on screen with an explicit stale warning.

Sequence checks reject late responses. Progress-only polls do not rebuild the keyboard
flight list, preserving focus and avoiding unnecessary DOM churn.

## 9. Reduced motion and visibility

With `prefers-reduced-motion: reduce`, continuous animation is disabled; authoritative
poll responses still update the map discretely. A client-side visual-pause control also
stops animation without pausing the server simulation. Hidden tabs stop polling and
animation work, abort an active request, and fetch fresh state when visible again.

## 10. Performance boundaries

The endpoint returns at most 500 candidate flights and executes one clock query plus
one bounded, related-object flight query. Only active, coordinate-complete movements
are serialized. The browser caches route geometry, limits animation to about 12.5
frames per second, and updates only the completed-route and aircraft sources on an
animation frame. Airports, full routes, and selected-route sources update only after
authoritative reconciliation or selection changes.

These boundaries are suitable for the portfolio dataset, not an internet-scale
tracking feed. The JSON response is intentionally non-cacheable and exposes no database
primary keys.

## 11. Failure states

The interface distinguishes initial loading, empty active network, malformed or failed
data, stale retained data, raster tile failure, fatal MapLibre initialization, and a
missing JavaScript bundle. A base-script handshake exposes a server-rendered link to
the flight board even when the map bundle never runs. A `<noscript>` fallback covers
JavaScript-disabled browsers.

MapLibre startup has a bounded wait, two automatic retries, and a manual renderer
retry. Raster failures do not tear down the operational map: the failed layer is
paused, a local geographic grid stays visible, and fresh raster sources are attempted
after 1.5, 5, and 15 seconds. The warning also offers an immediate manual retry. A
recovered layer is shown only after an image tile has produced a valid texture.

See [Map troubleshooting](MAP_TROUBLESHOOTING.md) for the small diagnostic bundle to
collect if a browser still presents a blank map.

## 12. What real ADS-B would require

A real tracking product would replace schedule interpolation with a licensed and
authenticated telemetry ingestion pipeline. It would need message ordering, aircraft
identity reconciliation, position freshness and quality indicators, streaming or
push delivery, rate and retention controls, geographic indexing, observability,
security review, and jurisdiction-specific data licensing and privacy compliance.
Server time and feed timestamps would need separate treatment, and users would need
clear loss-of-signal semantics. None of those capabilities are implied by Northstar.
