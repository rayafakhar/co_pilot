import { describe, expect, it, vi } from "vitest";

import { SOURCE_IDS, updateMapSources, waitForMapLoad } from "../map.js";
import { emptyFeatureCollection } from "../presentation.js";

function mapDouble() {
    const sources = new Map(
        Object.values(SOURCE_IDS).map((sourceId) => [
            sourceId,
            { setData: vi.fn() },
        ]),
    );
    return {
        getSource: (sourceId) => sources.get(sourceId),
        sources,
    };
}

describe("MapLibre source updates", () => {
    it("becomes operational when the style loads without waiting for raster tiles", async () => {
        const listeners = {};
        const map = {
            isStyleLoaded: () => false,
            on: (event, callback) => {
                listeners[event] = callback;
            },
            off: vi.fn(),
        };
        const ready = waitForMapLoad(map);
        listeners["style.load"]();
        await expect(ready).resolves.toBeUndefined();
        expect(map.off).toHaveBeenCalledWith("style.load", expect.any(Function));
    });

    it("rejects initialization instead of waiting forever for a missing style event", async () => {
        vi.useFakeTimers();
        const map = {
            isStyleLoaded: () => false,
            on: vi.fn(),
            off: vi.fn(),
        };
        const result = waitForMapLoad(map, { timeoutMs: 500 }).catch(
            (error) => error,
        );
        await vi.advanceTimersByTimeAsync(500);
        expect(await result).toEqual(
            new Error("MapLibre style initialization timed out."),
        );
        expect(map.off).toHaveBeenCalledWith("style.load", expect.any(Function));
        expect(map.off).toHaveBeenCalledWith("error", expect.any(Function));
        vi.useRealTimers();
    });

    it("updates only moving sources on an animation frame", () => {
        const map = mapDouble();
        const data = {
            routes: emptyFeatureCollection(),
            completedRoutes: emptyFeatureCollection(),
            aircraft: emptyFeatureCollection(),
        };
        updateMapSources(
            map,
            data,
            emptyFeatureCollection(),
            emptyFeatureCollection(),
            { staticSources: false },
        );
        expect(map.sources.get(SOURCE_IDS.completedRoutes).setData).toHaveBeenCalledOnce();
        expect(map.sources.get(SOURCE_IDS.aircraft).setData).toHaveBeenCalledOnce();
        expect(map.sources.get(SOURCE_IDS.airports).setData).not.toHaveBeenCalled();
        expect(map.sources.get(SOURCE_IDS.routes).setData).not.toHaveBeenCalled();
        expect(map.sources.get(SOURCE_IDS.selected).setData).not.toHaveBeenCalled();
    });

    it("updates all five persistent sources after authoritative reconciliation", () => {
        const map = mapDouble();
        const empty = emptyFeatureCollection();
        updateMapSources(
            map,
            { routes: empty, completedRoutes: empty, aircraft: empty },
            empty,
            empty,
        );
        for (const source of map.sources.values()) {
            expect(source.setData).toHaveBeenCalledOnce();
        }
    });
});
