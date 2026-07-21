import { emptyFeatureCollection } from "./presentation.js";

export const SOURCE_IDS = {
    airports: "active-airports",
    routes: "active-routes",
    completedRoutes: "completed-routes",
    aircraft: "active-aircraft",
    selected: "selected-flight",
};

export const LAYER_IDS = {
    routes: "route-lines",
    completedRoutes: "completed-route-lines",
    selected: "selected-route-line",
    airports: "airport-points",
    labels: "airport-labels",
    aircraftHalo: "aircraft-halo",
    aircraftIcon: "aircraft-icons",
};

export function createNetworkMap(maplibregl, container, config, onTileError) {
    const map = new maplibregl.Map({
        container,
        style: {
            version: 8,
            sources: {
                basemap: {
                    type: "raster",
                    tiles: [config.tileUrl],
                    tileSize: 256,
                    attribution: config.tileAttribution,
                },
            },
            layers: [
                {
                    id: "basemap",
                    type: "raster",
                    source: "basemap",
                    paint: {
                        "raster-saturation": -0.85,
                        "raster-contrast": 0.34,
                        "raster-brightness-min": 0.04,
                        "raster-brightness-max": 0.4,
                        "raster-opacity": 0.78,
                    },
                },
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
        if (event?.sourceId === "basemap" || /tile|raster|source/i.test(message)) {
            onTileError?.();
        }
    });
    return map;
}

export function waitForMapLoad(map) {
    if (map.isStyleLoaded()) return Promise.resolve();
    return new Promise((resolve, reject) => {
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
