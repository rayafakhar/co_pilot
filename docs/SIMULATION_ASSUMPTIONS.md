# Simulation assumptions

Northstar models operational plausibility for a portfolio demonstration. It is not a
flight-planning, dispatch, maintenance-control, or crew-management system.

## Route distance

The engine uses the Haversine formula with a mean Earth radius of 6,371.0088 km.
Flights are limited to 90% of the aircraft type's configured maximum range, leaving a
simple conservative reserve. The model does not calculate payload-range curves,
alternate fuel, winds, airways, restricted airspace, ETOPS, or holding.

## Block duration

Planned duration is the sum of:

- taxi-out: 14, 17, or 20 minutes by distance band;
- climb: 18, 22, or 25 minutes;
- cruise distance divided by typical speed with an efficiency adjustment;
- descent: 17, 20, or 23 minutes;
- taxi-in: 9, 11, or 13 minutes;
- variability: at least five minutes, normally 4% of cruise time.

Short haul is below 1,500 km, medium haul is below 4,000 km, and longer routes use the
long-haul allowances. The numbers are transparent simulation constants rather than
certified or operator-specific performance.

## Aircraft reference records

Aircraft type performance, capacity, crew, and dimensions are rounded illustrative
configuration values. They must not be used as exact manufacturer claims or for real
operations. The fictional operator and all registrations are synthetic.

## Operational variations

Probability controls are independent deterministic draws from the supplied seed.
Delays are usually 10–45 minutes, with a smaller chance of a 60–150 minute disruption.
Cancelled flights do not move an aircraft. Diversions select another distinct,
in-range airport and update the resulting location. Ferry legs are explicit.
Maintenance windows block the aircraft and push its readiness time.

## Time and status

All database timestamps are aware UTC. Airport-local display uses IANA timezone data.
The server instant is authoritative; a device clock is display-only. Journey progress
is interpolation over effective block time and is not a geographic position.
