import {
    aircraftBearing,
    buildGreatCircleRoute,
    pointAlongRoute,
    routeKey,
} from "./geometry.js";
import { correctedProgress, progressAtTime } from "./state.js";

export function emptyFeatureCollection() {
    return { type: "FeatureCollection", features: [] };
}

export function deriveUiState({
    loading = false,
    hasPayload = false,
    flightCount = 0,
    dataError = false,
    tileError = false,
    mapFatal = false,
} = {}) {
    return {
        showLoading: loading && !hasPayload,
        showEmpty: hasPayload && flightCount === 0 && !mapFatal,
        showDataError: dataError,
        showTileError: tileError,
        showFatal: mapFatal,
        stale: hasPayload && dataError,
    };
}

export function routeForFlight(cache, flight) {
    const key = routeKey(flight);
    if (!key) return null;
    if (!cache.has(key)) cache.set(key, buildGreatCircleRoute(flight));
    return cache.get(key);
}

function routeProperties(flight) {
    return {
        flight_number: flight.flight_number,
        status_code: flight.status_code,
        delayed: flight.delay_minutes > 0,
        diverted: flight.diverted,
    };
}

function completedRouteCoordinates(route, pointFeature, progress) {
    const coordinates = route.geometry.coordinates;
    if (progress <= 0) return [coordinates[0], coordinates[0]];
    if (progress >= 1) return coordinates;
    const approximateIndex = Math.max(
        0,
        Math.min(coordinates.length - 2, Math.floor((coordinates.length - 1) * progress)),
    );
    return [
        ...coordinates.slice(0, approximateIndex + 1),
        pointFeature.geometry.coordinates,
    ];
}

export function buildMapCollections(
    flights,
    simulationMilliseconds,
    routeCache,
    progressState,
    { authoritativeOnly = false, includeStatic = true } = {},
) {
    const routes = emptyFeatureCollection();
    const completedRoutes = emptyFeatureCollection();
    const aircraft = emptyFeatureCollection();
    const crew = emptyFeatureCollection();

    for (const flight of flights.values()) {
        const route = routeForFlight(routeCache, flight);
        if (!route) continue;
        const authoritativeProgress = progressAtTime(flight, simulationMilliseconds);
        const previousProgress = progressState.get(flight.flight_number);
        const progress = authoritativeOnly
            ? authoritativeProgress
            : correctedProgress(previousProgress, authoritativeProgress);
        progressState.set(flight.flight_number, progress);
        const position = pointAlongRoute(route, progress);
        if (!position) continue;
        const properties = routeProperties(flight);

        if (includeStatic) {
            routes.features.push({
                type: "Feature",
                geometry: route.geometry,
                properties,
            });
        }
        completedRoutes.features.push({
            type: "Feature",
            geometry: {
                type: "LineString",
                coordinates: completedRouteCoordinates(route, position, progress),
            },
            properties,
        });
        aircraft.features.push({
            type: "Feature",
            geometry: position.geometry,
            properties: {
                ...properties,
                bearing: aircraftBearing(route, progress),
                progress: Math.round(progress * 100),
            },
        });

        // Add crew marker features at the aircraft position
        if (flight.crew && flight.crew.length > 0) {
            for (let i = 0; i < flight.crew.length; i++) {
                const member = flight.crew[i];
                const crewPosition =
                    flight.crew.length === 1
                        ? "center"
                        : i === 0
                          ? "left"
                          : i === flight.crew.length - 1
                            ? "right"
                            : "center";
                crew.features.push({
                    type: "Feature",
                    geometry: {
                        type: "Point",
                        coordinates: position.geometry.coordinates,
                    },
                    properties: {
                        crew_icon: `crew-icon-${member.name.replace(/\s+/g, "-").toLowerCase()}`,
                        crew_position: crewPosition,
                        flight_number: flight.flight_number,
                    },
                });
            }
        }
    }
    return { routes, completedRoutes, aircraft, crew };
}

export function selectedRouteCollection(flight, routeCache) {
    const collection = emptyFeatureCollection();
    if (!flight) return collection;
    const route = routeForFlight(routeCache, flight);
    if (route) {
        collection.features.push({
            type: "Feature",
            geometry: route.geometry,
            properties: routeProperties(flight),
        });
    }
    return collection;
}

export function formatUtcDateTime(value) {
    const parsed = value instanceof Date ? value : new Date(value);
    if (!Number.isFinite(parsed.getTime())) return "Unavailable";
    return new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "medium",
        timeZone: "UTC",
    }).format(parsed);
}
