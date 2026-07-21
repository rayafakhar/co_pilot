import { routeKey } from "./geometry.js";

export function simulationTimeAt(
    serverTime,
    speedMultiplier,
    receivedAt,
    currentTime,
    paused = false,
) {
    const serverMilliseconds = Date.parse(serverTime);
    const speed = Number(speedMultiplier);
    if (!Number.isFinite(serverMilliseconds)) return null;
    if (paused || !Number.isFinite(speed) || speed <= 0) return serverMilliseconds;
    return serverMilliseconds + Math.max(0, currentTime - receivedAt) * speed;
}

export function progressAtTime(flight, simulationMilliseconds) {
    const departure = Date.parse(flight?.effective_departure);
    const arrival = Date.parse(flight?.effective_arrival);
    if (
        !Number.isFinite(simulationMilliseconds) ||
        !Number.isFinite(departure) ||
        !Number.isFinite(arrival) ||
        arrival <= departure
    ) {
        const serverProgress = Number(flight?.progress);
        return Number.isFinite(serverProgress)
            ? Math.max(0, Math.min(1, serverProgress / 100))
            : 0;
    }
    return Math.max(
        0,
        Math.min(1, (simulationMilliseconds - departure) / (arrival - departure)),
    );
}

export function createFlightState() {
    return {
        flights: new Map(),
        sequence: 0,
        generatedAt: 0,
    };
}

export function reconcileFlightState(currentState, payload, sequence) {
    const generatedAt = Date.parse(payload?.generated_at);
    if (
        !Number.isFinite(generatedAt) ||
        sequence <= currentState.sequence ||
        generatedAt < currentState.generatedAt
    ) {
        return { ...currentState, accepted: false };
    }

    const nextFlights = new Map();
    const added = [];
    const routeChanged = [];
    for (const flight of payload.flights ?? []) {
        if (!flight?.flight_number) continue;
        const previous = currentState.flights.get(flight.flight_number);
        const nextRouteKey = routeKey(flight);
        if (!nextRouteKey) continue;
        if (!previous) added.push(flight.flight_number);
        if (previous && previous.routeKey !== nextRouteKey) {
            routeChanged.push(flight.flight_number);
        }
        nextFlights.set(flight.flight_number, {
            ...flight,
            routeKey: nextRouteKey,
        });
    }
    const removed = [...currentState.flights.keys()].filter(
        (flightNumber) => !nextFlights.has(flightNumber),
    );
    return {
        flights: nextFlights,
        sequence,
        generatedAt,
        accepted: true,
        added,
        removed,
        routeChanged,
    };
}
