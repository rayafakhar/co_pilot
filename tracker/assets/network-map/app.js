import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import "./network-map.css";

import { fetchNetworkState } from "./api.js";
import {
    aircraftBearing,
    buildGreatCircleRoute,
    clampProgress,
    pointAlongRoute,
} from "./geometry.js";
import {
    createFlightState,
    progressAtTime,
    reconcileFlightState,
    simulationTimeAt,
} from "./state.js";

window.NorthstarNetworkMap = Object.freeze({
    maplibregl,
    fetchNetworkState,
    aircraftBearing,
    buildGreatCircleRoute,
    clampProgress,
    pointAlongRoute,
    createFlightState,
    progressAtTime,
    reconcileFlightState,
    simulationTimeAt,
});
document.documentElement.classList.add("network-map-module-ready");
