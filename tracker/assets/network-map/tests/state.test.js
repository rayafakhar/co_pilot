import { describe, expect, it } from "vitest";

import {
    correctedProgress,
    createFlightState,
    progressAtTime,
    reconcileFlightState,
    reconcileSelection,
    shouldAnimate,
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

    it("preserves selection only while the stable flight identity exists", () => {
        const state = reconcileFlightState(
            createFlightState(),
            { generated_at: "2026-07-19T10:00:10Z", flights: [baseFlight] },
            1,
        );
        expect(reconcileSelection("TS100", state.flights)).toBe("TS100");
        expect(reconcileSelection("MISSING", state.flights)).toBeNull();
    });

    it("eases small corrections and snaps significant authoritative changes", () => {
        expect(correctedProgress(0.5, 0.55)).toBeCloseTo(0.509);
        expect(correctedProgress(0.2, 0.8)).toBe(0.8);
        expect(correctedProgress(undefined, 0.4)).toBe(0.4);
    });

    it("disables animation for reduced motion, hidden pages, and client pause", () => {
        const active = { hasFlights: true };
        expect(shouldAnimate(active)).toBe(true);
        expect(shouldAnimate({ ...active, reducedMotion: true })).toBe(false);
        expect(shouldAnimate({ ...active, hidden: true })).toBe(false);
        expect(shouldAnimate({ ...active, clientPaused: true })).toBe(false);
        expect(shouldAnimate({ ...active, serverPaused: true })).toBe(false);
    });

    it("keeps server time advancing when only client visual motion is paused", () => {
        const serverTime = simulationTimeAt(
            "2026-07-19T10:00:00Z",
            2,
            1_000,
            6_000,
            false,
        );
        expect(serverTime).toBe(Date.parse("2026-07-19T10:00:10Z"));
        expect(shouldAnimate({ hasFlights: true, clientPaused: true })).toBe(false);
    });

    it("skips one malformed flight without dropping valid state", () => {
        const state = reconcileFlightState(
            createFlightState(),
            {
                generated_at: "2026-07-19T10:00:10Z",
                flights: [{ flight_number: "BROKEN" }, baseFlight],
            },
            1,
        );
        expect(state.accepted).toBe(true);
        expect(state.skipped).toBe(1);
        expect([...state.flights.keys()]).toEqual(["TS100"]);
    });
});
