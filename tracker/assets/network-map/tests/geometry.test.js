import { describe, expect, it } from "vitest";

import {
    aircraftBearing,
    buildGreatCircleRoute,
    clampProgress,
    pointAlongRoute,
    routeKey,
    routeLengthKm,
} from "../geometry.js";

function flight(origin, destination) {
    return {
        origin: { coordinates: origin },
        result_destination: { coordinates: destination },
    };
}

describe("great-circle geometry", () => {
    it("clamps progress and rejects non-numeric input", () => {
        expect(clampProgress(-1)).toBe(0);
        expect(clampProgress(0.4)).toBe(0.4);
        expect(clampProgress(2)).toBe(1);
        expect(clampProgress("bad")).toBe(0);
    });

    it("creates a curved route with position and bearing", () => {
        const route = buildGreatCircleRoute(flight([-73.7781, 40.6413], [-0.4543, 51.47]));
        expect(route.geometry.coordinates.length).toBeGreaterThan(2);
        expect(routeLengthKm(route)).toBeGreaterThan(5_000);
        const midpoint = pointAlongRoute(route, 0.5);
        expect(midpoint.geometry.coordinates).toHaveLength(2);
        expect(Number.isFinite(aircraftBearing(route, 0.5))).toBe(true);
    });

    it("handles a zero-length route without throwing", () => {
        const route = buildGreatCircleRoute(flight([10, 20], [10, 20]));
        expect(routeLengthKm(route)).toBe(0);
        expect(pointAlongRoute(route, 0.7).geometry.coordinates).toEqual([10, 20]);
    });

    it("returns null for missing or invalid coordinates", () => {
        expect(buildGreatCircleRoute(flight(null, [0, 0]))).toBeNull();
        expect(buildGreatCircleRoute(flight([181, 0], [0, 0]))).toBeNull();
        expect(routeKey(flight([0, 0], null))).toBeNull();
    });

    it("unwraps an antimeridian route without a world-spanning segment", () => {
        const route = buildGreatCircleRoute(flight([170, 35], [-170, 40]));
        const longitudes = route.geometry.coordinates.map((coordinate) => coordinate[0]);
        const segmentDeltas = longitudes.slice(1).map((value, index) => value - longitudes[index]);
        expect(Math.max(...segmentDeltas.map(Math.abs))).toBeLessThan(180);
        expect(Math.max(...longitudes)).toBeGreaterThan(180);
    });
});
