import { describe, expect, it } from "vitest";

import {
    createFlightState,
    progressAtTime,
    reconcileFlightState,
    simulationTimeAt,
} from "../state.js";

const baseFlight = {
    flight_number: "TS100",
    origin: { coordinates: [0, 0] },
    result_destination: { coordinates: [10, 10] },
    effective_departure: "2026-07-19T10:00:00Z",
    effective_arrival: "2026-07-19T12:00:00Z",
    progress: 50,
};

describe("simulation state", () => {
    it("advances server time using monotonic elapsed time and speed", () => {
        expect(simulationTimeAt("2026-07-19T10:00:00Z", 5, 1_000, 3_000)).toBe(
            Date.parse("2026-07-19T10:00:10Z"),
        );
        expect(simulationTimeAt("2026-07-19T10:00:00Z", 5, 1_000, 3_000, true)).toBe(
            Date.parse("2026-07-19T10:00:00Z"),
        );
    });

    it("calculates progress and safely handles zero-duration records", () => {
        expect(progressAtTime(baseFlight, Date.parse("2026-07-19T11:00:00Z"))).toBe(0.5);
        expect(
            progressAtTime(
                {
                    ...baseFlight,
                    effective_arrival: baseFlight.effective_departure,
                    progress: 42,
                },
                Date.parse("2026-07-19T11:00:00Z"),
            ),
        ).toBe(0.42);
    });

    it("reconciles by stable flight number and detects route changes", () => {
        const initial = reconcileFlightState(
            createFlightState(),
            { generated_at: "2026-07-19T10:00:00Z", flights: [baseFlight] },
            1,
        );
        expect(initial.added).toEqual(["TS100"]);
        const changed = reconcileFlightState(
            initial,
            {
                generated_at: "2026-07-19T10:00:10Z",
                flights: [
                    {
                        ...baseFlight,
                        result_destination: { coordinates: [20, 20] },
                    },
                ],
            },
            2,
        );
        expect(changed.routeChanged).toEqual(["TS100"]);
        expect(changed.flights.has("TS100")).toBe(true);
    });

    it("removes absent flights and rejects stale responses", () => {
        const initial = reconcileFlightState(
            createFlightState(),
            { generated_at: "2026-07-19T10:00:10Z", flights: [baseFlight] },
            2,
        );
        const stale = reconcileFlightState(
            initial,
            { generated_at: "2026-07-19T10:00:00Z", flights: [] },
            3,
        );
        expect(stale.accepted).toBe(false);
        expect(stale.flights.has("TS100")).toBe(true);
        const removed = reconcileFlightState(
            initial,
            { generated_at: "2026-07-19T10:00:20Z", flights: [] },
            3,
        );
        expect(removed.removed).toEqual(["TS100"]);
    });
});
