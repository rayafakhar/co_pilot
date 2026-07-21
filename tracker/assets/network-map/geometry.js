import { along } from "@turf/along";
import { bearing } from "@turf/bearing";
import { greatCircle } from "@turf/great-circle";
import { lineString, point } from "@turf/helpers";
import { length } from "@turf/length";

export function clampProgress(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return 0;
    return Math.max(0, Math.min(1, numeric));
}

export function isCoordinate(value) {
    return (
        Array.isArray(value) &&
        value.length >= 2 &&
        Number.isFinite(Number(value[0])) &&
        Number.isFinite(Number(value[1])) &&
        Math.abs(Number(value[0])) <= 180 &&
        Math.abs(Number(value[1])) <= 90
    );
}

export function routeKey(flight) {
    const origin = flight?.origin?.coordinates;
    const destination = flight?.result_destination?.coordinates;
    if (!isCoordinate(origin) || !isCoordinate(destination)) return null;
    return [origin[0], origin[1], destination[0], destination[1]].join(":");
}

function unwrapCoordinates(coordinates) {
    const unwrapped = [];
    for (const coordinate of coordinates) {
        if (!isCoordinate(coordinate)) continue;
        let longitude = Number(coordinate[0]);
        const latitude = Number(coordinate[1]);
        if (unwrapped.length) {
            const previousLongitude = unwrapped.at(-1)[0];
            while (longitude - previousLongitude > 180) longitude -= 360;
            while (longitude - previousLongitude < -180) longitude += 360;
        }
        unwrapped.push([longitude, latitude]);
    }
    return unwrapped;
}

export function buildGreatCircleRoute(flight, { pointCount = 128 } = {}) {
    const origin = flight?.origin?.coordinates;
    const destination = flight?.result_destination?.coordinates;
    if (!isCoordinate(origin) || !isCoordinate(destination)) return null;
    if (Number(origin[0]) === Number(destination[0]) && Number(origin[1]) === Number(destination[1])) {
        return lineString([origin.map(Number), destination.map(Number)]);
    }

    const generated = greatCircle(point(origin), point(destination), {
        npoints: Math.max(2, Math.round(pointCount)),
        offset: 10,
    });
    const segments =
        generated.geometry.type === "MultiLineString"
            ? generated.geometry.coordinates
            : [generated.geometry.coordinates];
    const coordinates = unwrapCoordinates(segments.flat());
    return coordinates.length >= 2 ? lineString(coordinates) : null;
}

export function routeLengthKm(route) {
    if (!route) return 0;
    const result = length(route, { units: "kilometers" });
    return Number.isFinite(result) ? result : 0;
}

export function pointAlongRoute(route, progress) {
    if (!route?.geometry?.coordinates?.length) return null;
    const distance = routeLengthKm(route);
    if (distance <= 0) return point(route.geometry.coordinates[0]);
    return along(route, distance * clampProgress(progress), {
        units: "kilometers",
    });
}

export function aircraftBearing(route, progress) {
    const current = pointAlongRoute(route, progress);
    const ahead = pointAlongRoute(route, clampProgress(progress + 0.002));
    if (!current || !ahead) return 0;
    const result = bearing(current, ahead);
    return Number.isFinite(result) ? result : 0;
}
