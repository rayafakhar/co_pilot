import { emptyFeatureCollection } from "./presentation.js";

export const SOURCE_IDS = {
    airports: "active-airports",
    routes: "active-routes",
    completedRoutes: "completed-routes",
    aircraft: "active-aircraft",
    selected: "selected-flight",
    crew: "active-crew",
};

export const LAYER_IDS = {
    routes: "route-lines",
    completedRoutes: "completed-route-lines",
    selected: "selected-route-line",
    airports: "airport-points",
    labels: "airport-labels",
    aircraftHalo: "aircraft-halo",
    aircraftIcon: "aircraft-icons",
    crewMarkers: "crew-markers",
};

export const BASEMAP_SOURCE_ID = "basemap";
export const BASEMAP_LAYER_ID = "basemap";

const BASEMAP_OPACITY = 0.78;

function basemapSource(config) {
    return {
        type: "raster",
        tiles: [config.tileUrl],
        tileSize: 256,
        attribution: config.tileAttribution,
    };
}

function basemapLayer({ loading = false } = {}) {
    return {
        id: BASEMAP_LAYER_ID,
        type: "raster",
        source: BASEMAP_SOURCE_ID,
        paint: {
            "raster-saturation": -0.85,
            "raster-contrast": 0.34,
            "raster-brightness-min": 0.04,
            "raster-brightness-max": 0.4,
            "raster-opacity": loading ? 0 : BASEMAP_OPACITY,
        },
    };
}

function fallbackGrid() {
    const features = [];
    for (let longitude = -180; longitude <= 180; longitude += 30) {
        features.push({
            type: "Feature",
            properties: {},
            geometry: {
                type: "LineString",
                coordinates: [
                    [longitude, -80],
                    [longitude, 80],
                ],
            },
        });
    }
    for (let latitude = -60; latitude <= 80; latitude += 20) {
        features.push({
            type: "Feature",
            properties: {},
            geometry: {
                type: "LineString",
                coordinates: [
                    [-180, latitude],
                    [180, latitude],
                ],
            },
        });
    }
    return { type: "FeatureCollection", features };
}

export function createNetworkMap(
    maplibregl,
    container,
    config,
    onTileError,
    onTileReady,
) {
    const map = new maplibregl.Map({
        container,
        style: {
            version: 8,
            sources: {
                "fallback-grid": {
                    type: "geojson",
                    data: fallbackGrid(),
                },
                [BASEMAP_SOURCE_ID]: basemapSource(config),
            },
            layers: [
                {
                    id: "fallback-background",
                    type: "background",
                    paint: { "background-color": "#061019" },
                },
                {
                    id: "fallback-grid",
                    type: "line",
                    source: "fallback-grid",
                    paint: {
                        "line-color": "rgba(83,199,237,0.16)",
                        "line-width": 1,
                        "line-dasharray": [2, 3],
                    },
                },
                basemapLayer(),
            ],
        },
        center: [0, 24],
        zoom: 1.35,
        minZoom: 1,
        maxZoom: 12,
        attributionControl: false,
        cooperativeGestures: true,
    });
    map.addControl(
        new maplibregl.NavigationControl({ showCompass: false }),
        "bottom-left",
    );
    map.addControl(
        new maplibregl.AttributionControl({ compact: true }),
        "bottom-right",
    );
    map.on("error", (event) => {
        const message = String(event?.error?.message ?? "");
        if (
            event?.sourceId === BASEMAP_SOURCE_ID ||
            /tile|raster/i.test(message)
        ) {
            onTileError?.();
        }
    });
    map.on("sourcedata", (event) => {
        if (
            event?.sourceId === BASEMAP_SOURCE_ID &&
            event?.tile?.texture
        ) {
            onTileReady?.();
        }
    });
    return map;
}

export function setBasemapVisible(map, visible) {
    if (!map?.getLayer?.(BASEMAP_LAYER_ID)) return false;
    map.setPaintProperty(
        BASEMAP_LAYER_ID,
        "raster-opacity",
        visible ? BASEMAP_OPACITY : 0,
    );
    return true;
}

export function reloadBasemap(map, config) {
    if (
        !map?.getSource?.(BASEMAP_SOURCE_ID) ||
        !map?.getLayer?.(BASEMAP_LAYER_ID) ||
        !config?.tileUrl
    ) {
        return false;
    }
    setBasemapVisible(map, false);
    map.removeLayer(BASEMAP_LAYER_ID);
    map.removeSource(BASEMAP_SOURCE_ID);
    map.addSource(BASEMAP_SOURCE_ID, basemapSource(config));
    const firstOperationalLayer = map.getLayer(LAYER_IDS.routes)
        ? LAYER_IDS.routes
        : undefined;
    map.addLayer(basemapLayer({ loading: true }), firstOperationalLayer);
    return true;
}

export function waitForMapLoad(map, { timeoutMs = 6_000 } = {}) {
    if (map.isStyleLoaded()) return Promise.resolve();
    return new Promise((resolve, reject) => {
        const timeoutId = globalThis.setTimeout(() => {
            cleanup();
            reject(new Error("MapLibre style initialization timed out."));
        }, timeoutMs);
        const onLoad = () => {
            cleanup();
            resolve();
        };
        const onError = (event) => {
            if (!map.style) {
                cleanup();
                reject(event?.error ?? new Error("MapLibre failed to initialize."));
            }
        };
        const cleanup = () => {
            globalThis.clearTimeout(timeoutId);
            map.off("style.load", onLoad);
            map.off("error", onError);
        };
        map.on("style.load", onLoad);
        map.on("error", onError);
    });
}

function loadImage(url) {
    return new Promise((resolve, reject) => {
        const image = new Image(64, 64);
        image.onload = () => resolve(image);
        image.onerror = () => reject(new Error("Aircraft icon could not be loaded."));
        image.src = url;
    });
}

/**
 * Create a map pin-shaped icon with a profile picture inside.
 * Returns an ImageData object for map.addImage().
 */
function createCrewPinImage(image, size = 64) {
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext("2d");

    // Draw map pin shape
    const cx = size / 2;
    const cy = size / 2;
    const radius = size * 0.42;
    const tipY = size * 0.82;

    // Pin body (dark background with sky border)
    ctx.beginPath();
    ctx.arc(cx, cy - radius * 0.15, radius, 0, Math.PI * 2);
    ctx.lineTo(cx, tipY);
    ctx.closePath();

    // Fill with dark color
    ctx.fillStyle = "#071019";
    ctx.fill();

    // Border
    ctx.strokeStyle = "#53c7ed";
    ctx.lineWidth = 2;
    ctx.stroke();

    // Draw profile picture inside circle
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy - radius * 0.15, radius * 0.72, 0, Math.PI * 2);
    ctx.clip();

    // Draw image centered and scaled
    const imgSize = radius * 1.5;
    const imgX = cx - imgSize / 2;
    const imgY = cy - radius * 0.15 - imgSize / 2;
    ctx.drawImage(image, imgX, imgY, imgSize, imgSize);
    ctx.restore();

    // Add a subtle inner glow
    ctx.beginPath();
    ctx.arc(cx, cy - radius * 0.15, radius * 0.72, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(83, 199, 237, 0.4)";
    ctx.lineWidth = 1;
    ctx.stroke();

    return canvas.getContext("2d").getImageData(0, 0, size, size);
}

/**
 * Create a default silhouette icon for crew without profile pictures.
 */
function createDefaultCrewIcon(role, size = 64) {
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext("2d");

    const cx = size / 2;
    const cy = size / 2;
    const radius = size * 0.42;

    // Pin body
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.closePath();
    ctx.fillStyle = "#071019";
    ctx.fill();
    ctx.strokeStyle = "#53c7ed";
    ctx.lineWidth = 2;
    ctx.stroke();

    // Silhouette (pilot/flight attendant)
    ctx.fillStyle = "#53c7ed";
    // Head
    ctx.beginPath();
    ctx.arc(cx, cy - radius * 0.2, radius * 0.3, 0, Math.PI * 2);
    ctx.fill();
    // Body
    ctx.beginPath();
    ctx.ellipse(cx, cy + radius * 0.5, radius * 0.45, radius * 0.35, 0, 0, Math.PI * 2);
    ctx.fill();

    return ctx.getImageData(0, 0, size, size);
}

/**
 * Load a profile image and cache the crew marker icon.
 */
const crewImageCache = new Map();

async function buildCrewMarkerImage(url, role) {
    if (!url) return createDefaultCrewIcon(role);

    try {
        const img = await loadImage(url);
        return createCrewPinImage(img);
    } catch {
        return createDefaultCrewIcon(role);
    }
}

export async function loadAndCacheCrewIcon(map, url, iconId, role = null) {
    if (map.hasImage(iconId)) return;

    const cacheKey = url || `default:${role ?? "crew"}`;
    if (!crewImageCache.has(cacheKey)) {
        crewImageCache.set(cacheKey, buildCrewMarkerImage(url, role));
    }

    const imageData = await crewImageCache.get(cacheKey);
    if (!map.hasImage(iconId)) {
        map.addImage(iconId, imageData, { pixelRatio: 2 });
    }
}

export async function installOperationalLayers(map, aircraftIconUrl) {
    for (const sourceId of Object.values(SOURCE_IDS)) {
        map.addSource(sourceId, {
            type: "geojson",
            data: emptyFeatureCollection(),
        });
    }

    map.addLayer({
        id: LAYER_IDS.routes,
        type: "line",
        source: SOURCE_IDS.routes,
        paint: {
            "line-color": [
                "case",
                ["get", "diverted"],
                "#ff6b63",
                ["get", "delayed"],
                "#ffbf47",
                "#53c7ed",
            ],
            "line-width": 1.5,
            "line-opacity": 0.35,
        },
    });
    map.addLayer({
        id: LAYER_IDS.completedRoutes,
        type: "line",
        source: SOURCE_IDS.completedRoutes,
        paint: {
            "line-color": [
                "case",
                ["get", "diverted"],
                "#ff6b63",
                ["get", "delayed"],
                "#ffbf47",
                "#57d99b",
            ],
            "line-width": 2.8,
            "line-opacity": 0.9,
        },
    });
    map.addLayer({
        id: LAYER_IDS.selected,
        type: "line",
        source: SOURCE_IDS.selected,
        paint: {
            "line-color": "#f4f8fb",
            "line-width": 5,
            "line-opacity": 0.85,
            "line-blur": 0.4,
        },
    });
    map.addLayer({
        id: LAYER_IDS.airports,
        type: "circle",
        source: SOURCE_IDS.airports,
        paint: {
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 3, 6, 6],
            "circle-color": "#071019",
            "circle-stroke-color": "#53c7ed",
            "circle-stroke-width": 1.5,
        },
    });
    map.addLayer({
        id: LAYER_IDS.labels,
        type: "symbol",
        source: SOURCE_IDS.airports,
        minzoom: 2.3,
        layout: {
            "icon-image": ["get", "label_icon"],
            "icon-offset": [0, 22],
            "icon-allow-overlap": false,
            "icon-ignore-placement": false,
        },
    });
    map.addLayer({
        id: LAYER_IDS.aircraftHalo,
        type: "circle",
        source: SOURCE_IDS.aircraft,
        paint: {
            "circle-radius": 13,
            "circle-color": "rgba(7,16,25,0.72)",
            "circle-stroke-color": [
                "case",
                ["get", "diverted"],
                "#ff6b63",
                ["get", "delayed"],
                "#ffbf47",
                "#53c7ed",
            ],
            "circle-stroke-width": 1.5,
        },
    });

    try {
        const aircraftImage = await loadImage(aircraftIconUrl);
        map.addImage("northstar-aircraft", aircraftImage, { pixelRatio: 2 });
        map.addLayer({
            id: LAYER_IDS.aircraftIcon,
            type: "symbol",
            source: SOURCE_IDS.aircraft,
            layout: {
                "icon-image": "northstar-aircraft",
                "icon-size": ["interpolate", ["linear"], ["zoom"], 1, 0.42, 8, 0.68],
                "icon-allow-overlap": true,
                "icon-ignore-placement": true,
                "icon-rotate": ["get", "bearing"],
                "icon-rotation-alignment": "map",
            },
        });
    } catch {
        // The colored halo remains a useful, clickable aircraft fallback.
    }

    // Crew markers layer - shows crew profile icons as markers on flights
    map.addLayer({
        id: LAYER_IDS.crewMarkers,
        type: "symbol",
        source: SOURCE_IDS.crew,
        layout: {
            "icon-image": ["get", "crew_icon"],
            "icon-size": ["interpolate", ["linear"], ["zoom"], 1, 0.35, 6, 0.55, 10, 0.7],
            "icon-allow-overlap": true,
            "icon-ignore-placement": true,
            "icon-offset": [0, -8],
        },
        paint: {
            "icon-opacity": 0.88,
        },
    });
}

export function prepareAirportLabels(map, featureCollection) {
    const features = (featureCollection?.features ?? []).map((feature) => {
        const code = String(feature?.properties?.code ?? "").slice(0, 4);
        const imageId = `airport-label-${code}`;
        if (code && !map.hasImage(imageId)) {
            const canvas = document.createElement("canvas");
            canvas.width = 104;
            canvas.height = 40;
            const context = canvas.getContext("2d");
            context.clearRect(0, 0, canvas.width, canvas.height);
            context.fillStyle = "rgba(7, 16, 25, 0.88)";
            context.fillRect(1, 1, 102, 38);
            context.strokeStyle = "#315166";
            context.lineWidth = 2;
            context.strokeRect(1, 1, 102, 38);
            context.fillStyle = "#dce9f1";
            context.font = "700 22px monospace";
            context.textAlign = "center";
            context.textBaseline = "middle";
            context.fillText(code, 52, 21);
            map.addImage(imageId, context.getImageData(0, 0, 104, 40), {
                pixelRatio: 2,
            });
        }
        return {
            ...feature,
            properties: {
                ...feature.properties,
                label_icon: imageId,
            },
        };
    });
    return { type: "FeatureCollection", features };
}

export function updateMapSources(
    map,
    data,
    airports,
    selectedRoute,
    { staticSources = true } = {},
) {
    if (staticSources) {
        map.getSource(SOURCE_IDS.airports)?.setData(airports);
        map.getSource(SOURCE_IDS.routes)?.setData(data.routes);
        map.getSource(SOURCE_IDS.selected)?.setData(selectedRoute);
    }
    map.getSource(SOURCE_IDS.completedRoutes)?.setData(data.completedRoutes);
    map.getSource(SOURCE_IDS.aircraft)?.setData(data.aircraft);
    map.getSource(SOURCE_IDS.crew)?.setData(
        data.crew ?? emptyFeatureCollection(),
    );
}

export function setLayerVisibility(map, layerIds, visible) {
    for (const layerId of layerIds) {
        if (map.getLayer(layerId)) {
            map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
        }
    }
}

export function fitNetworkBounds(map, bounds) {
    if (!bounds?.southwest || !bounds?.northeast) return;
    const samePoint =
        bounds.southwest[0] === bounds.northeast[0] &&
        bounds.southwest[1] === bounds.northeast[1];
    if (samePoint) {
        map.easeTo({ center: bounds.southwest, zoom: 5, duration: 500 });
    } else {
        map.fitBounds([bounds.southwest, bounds.northeast], {
            padding: 72,
            maxZoom: 6,
            duration: 700,
        });
    }
}
