import { describe, expect, it, vi } from "vitest";

import {
    BASEMAP_LAYER_ID,
    BASEMAP_SOURCE_ID,
    createNetworkMap,
    LAYER_IDS,
    reloadBasemap,
    setBasemapVisible,
    SOURCE_IDS,
    updateMapSources,
    waitForMapLoad,
} from "../map.js";
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
    it("keeps an operational grid visible and reports raster recovery", () => {
        const listeners = {};
        const map = {
            addControl: vi.fn(),
            on: vi.fn((event, callback) => {
                listeners[event] = callback;
            }),
        };
        const maplibregl = {
            Map: vi.fn(function mapConstructor() {
                return map;
            }),
            NavigationControl: vi.fn(function navigationControl() {}),
            AttributionControl: vi.fn(function attributionControl() {}),
        };
        const onTileError = vi.fn();
        const onTileReady = vi.fn();

        createNetworkMap(
            maplibregl,
            "container",
            {
                tileUrl: "https://tiles.test/{z}/{x}/{y}.png",
                tileAttribution: "Test tiles",
            },
            onTileError,
            onTileReady,
        );

        const options = maplibregl.Map.mock.calls[0][0];
        expect(options.style.sources["fallback-grid"].data.features.length).toBe(21);
        expect(options.style.layers.map((layer) => layer.id).slice(0, 3)).toEqual([
            "fallback-background",
            "fallback-grid",
            "basemap",
        ]);
        listeners.error({ sourceId: BASEMAP_SOURCE_ID, error: new Error("tile") });
        listeners.sourcedata({
            sourceId: BASEMAP_SOURCE_ID,
            tile: { texture: {} },
        });
        expect(onTileError).toHaveBeenCalledOnce();
        expect(onTileReady).toHaveBeenCalledOnce();
    });

    it("recreates a failed raster source with rendering paused", () => {
        const map = {
            addLayer: vi.fn(),
            addSource: vi.fn(),
            getLayer: vi.fn((layerId) =>
                [BASEMAP_LAYER_ID, LAYER_IDS.routes].includes(layerId)
                    ? {}
                    : null,
            ),
            getSource: vi.fn(() => ({})),
            removeLayer: vi.fn(),
            removeSource: vi.fn(),
            setPaintProperty: vi.fn(),
        };
        const config = {
            tileUrl: "https://tiles.test/{z}/{x}/{y}.png",
            tileAttribution: "Test tiles",
        };
        expect(reloadBasemap(map, config)).toBe(true);
        expect(map.setPaintProperty).toHaveBeenCalledWith(
            BASEMAP_LAYER_ID,
            "raster-opacity",
            0,
        );
        expect(map.removeLayer).toHaveBeenCalledWith(BASEMAP_LAYER_ID);
        expect(map.removeSource).toHaveBeenCalledWith(BASEMAP_SOURCE_ID);
        expect(map.addSource).toHaveBeenCalledWith(BASEMAP_SOURCE_ID, {
            type: "raster",
            tiles: [config.tileUrl],
            tileSize: 256,
            attribution: config.tileAttribution,
        });
        expect(map.addLayer).toHaveBeenCalledWith(
            expect.objectContaining({
                id: BASEMAP_LAYER_ID,
                paint: expect.objectContaining({ "raster-opacity": 0 }),
            }),
            LAYER_IDS.routes,
        );
        expect(reloadBasemap({ getSource: () => null }, config)).toBe(false);
    });

    it("shows and hides the basemap without disabling tile loading", () => {
        const map = {
            getLayer: vi.fn(() => ({})),
            setPaintProperty: vi.fn(),
        };
        expect(setBasemapVisible(map, false)).toBe(true);
        expect(setBasemapVisible(map, true)).toBe(true);
        expect(map.setPaintProperty).toHaveBeenNthCalledWith(
            1,
            BASEMAP_LAYER_ID,
            "raster-opacity",
            0,
        );
        expect(map.setPaintProperty).toHaveBeenNthCalledWith(
            2,
            BASEMAP_LAYER_ID,
            "raster-opacity",
            0.78,
        );
    });

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
            crew: emptyFeatureCollection(),
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
        expect(map.sources.get(SOURCE_IDS.crew).setData).toHaveBeenCalledOnce();
        expect(map.sources.get(SOURCE_IDS.airports).setData).not.toHaveBeenCalled();
        expect(map.sources.get(SOURCE_IDS.routes).setData).not.toHaveBeenCalled();
        expect(map.sources.get(SOURCE_IDS.selected).setData).not.toHaveBeenCalled();
    });

    it("updates all six persistent sources after authoritative reconciliation", () => {
        const map = mapDouble();
        const empty = emptyFeatureCollection();
        updateMapSources(
            map,
            {
                routes: empty,
                completedRoutes: empty,
                aircraft: empty,
                crew: empty,
            },
            empty,
            empty,
        );
        for (const source of map.sources.values()) {
            expect(source.setData).toHaveBeenCalledOnce();
        }
    });
});
