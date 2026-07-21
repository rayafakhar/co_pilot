import { describe, expect, it } from "vitest";

import {
    buildMapCollections,
    deriveUiState,
    routeForFlight,
    selectedRouteCollection,
} from "../presentation.js";

const flight = {
    flight_number: "TS100",
    status_code: "en_route",
    status_label: "En route",
    delay_minutes: 0,
    diverted: false,
    origin: { coordinates: [-73.7781, 40.6413] },
    result_destination: { coordinates: [-0.4543, 51.47] },
    effective_departure: "2026-07-19T10:00:00Z",
    effective_arrival: "2026-07-19T12:00:00Z",
    progress: 50,
};

describe("map presentation state", () => {
    it("represents initial, empty, API error, tile error, and fatal states separately", () => {
        expect(deriveUiState({ loading: true }).showLoading).toBe(true);
        expect(deriveUiState({ hasPayload: true, flightCount: 0 }).showEmpty).toBe(true);
        expect(
            deriveUiState({ hasPayload: true, flightCount: 1, dataError: true }),
        ).toMatchObject({ showDataError: true, stale: true, showTileError: false });
        expect(deriveUiState({ tileError: true })).toMatchObject({
            showTileError: true,
            showDataError: false,
        });
        expect(deriveUiState({ mapFatal: true }).showFatal).toBe(true);
    });

    it("caches unchanged routes and replaces geometry after diversion", () => {
        const cache = new Map();
        const first = routeForFlight(cache, flight);
        const unchanged = routeForFlight(cache, { ...flight });
        const diverted = routeForFlight(cache, {
            ...flight,
            diverted: true,
            result_destination: { coordinates: [2.5479, 49.0097] },
        });
        expect(unchanged).toBe(first);
        expect(diverted).not.toBe(first);
        expect(cache.size).toBe(2);
    });

    it("builds persistent source collections for active aircraft", () => {
        const collections = buildMapCollections(
            new Map([[flight.flight_number, flight]]),
            Date.parse("2026-07-19T11:00:00Z"),
            new Map(),
            new Map(),
            { authoritativeOnly: true },
        );
        expect(collections.routes.features).toHaveLength(1);
        expect(collections.completedRoutes.features).toHaveLength(1);
        expect(collections.aircraft.features).toHaveLength(1);
        expect(collections.aircraft.features[0].properties).toMatchObject({
            flight_number: "TS100",
            progress: 50,
        });
    });

    it("skips static route features during animation-only source updates", () => {
        const collections = buildMapCollections(
            new Map([[flight.flight_number, flight]]),
            Date.parse("2026-07-19T11:00:01Z"),
            new Map(),
            new Map(),
            { includeStatic: false },
        );
        expect(collections.routes.features).toEqual([]);
        expect(collections.completedRoutes.features).toHaveLength(1);
        expect(collections.aircraft.features).toHaveLength(1);
    });

    it("returns empty collections and selection when no flights are active", () => {
        const collections = buildMapCollections(
            new Map(),
            Date.parse("2026-07-19T11:00:00Z"),
            new Map(),
            new Map(),
        );
        expect(collections.routes.features).toEqual([]);
        expect(collections.aircraft.features).toEqual([]);
        expect(selectedRouteCollection(null, new Map()).features).toEqual([]);
    });

    it("highlights the selected flight using its cached route", () => {
        const cache = new Map();
        const selected = selectedRouteCollection(flight, cache);
        expect(selected.features).toHaveLength(1);
        expect(selected.features[0].properties.flight_number).toBe("TS100");
        expect(cache.size).toBe(1);
    });
});
