import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import "./network-map.css";

import { fetchNetworkState } from "./api.js";
import {
    createNetworkMap,
    fitNetworkBounds,
    installOperationalLayers,
    LAYER_IDS,
    prepareAirportLabels,
    setLayerVisibility,
    updateMapSources,
    waitForMapLoad,
} from "./map.js";
import {
    buildMapCollections,
    deriveUiState,
    emptyFeatureCollection,
    formatUtcDateTime,
    selectedRouteCollection,
} from "./presentation.js";
import {
    createFlightState,
    reconcileFlightState,
    reconcileSelection,
    shouldAnimate,
    simulationTimeAt,
} from "./state.js";

const root = document.querySelector("[data-network-map]");

if (root) {
    const configNode = document.querySelector("#network-map-config");
    let config = null;
    try {
        config = JSON.parse(configNode?.textContent ?? "");
    } catch {
        config = null;
    }

    const dom = {
        map: root.querySelector("#flight-network-map"),
        loading: root.querySelector("[data-map-loading]"),
        empty: root.querySelector("[data-map-empty]"),
        fatal: root.querySelector("[data-map-fatal]"),
        dataError: root.querySelector("[data-map-data-error]"),
        tileError: root.querySelector("[data-map-tile-error]"),
        feedState: root.querySelector("[data-feed-state]"),
        feedMessage: root.querySelector("[data-feed-message]"),
        simulationTime: root.querySelector("[data-map-simulation-time]"),
        activeList: root.querySelector("[data-active-flight-list]"),
        selectedEmpty: root.querySelector("[data-selected-empty]"),
        selectedPanel: root.querySelector("[data-selected-panel]"),
        clearButton: root.querySelector('[data-map-action="clear"]'),
        selected: {
            status: root.querySelector("[data-selected-status]"),
            flightNumber: root.querySelector("[data-selected-flight-number]"),
            progress: root.querySelector("[data-selected-progress]"),
            aircraft: root.querySelector("[data-selected-aircraft]"),
            origin: root.querySelector("[data-selected-origin]"),
            planned: root.querySelector("[data-selected-planned]"),
            result: root.querySelector("[data-selected-result]"),
            resultRow: root.querySelector("[data-selected-result-row]"),
            delay: root.querySelector("[data-selected-delay]"),
            departure: root.querySelector("[data-selected-departure]"),
            arrival: root.querySelector("[data-selected-arrival]"),
            simulation: root.querySelector("[data-selected-simulation]"),
            flightUrl: root.querySelector("[data-selected-flight-url]"),
            aircraftUrl: root.querySelector("[data-selected-aircraft-url]"),
        },
    };

    let flightState = createFlightState();
    let latestPayload = null;
    let selectedFlightNumber = null;
    let map = null;
    let mapReady = false;
    let mapFatal = false;
    let tileError = false;
    let dataError = false;
    let requestController = null;
    let requestSequence = 0;
    let pollTimer = null;
    let clockTimer = null;
    let animationFrame = null;
    let lastFrameAt = 0;
    let receivedAt = performance.now();
    let clientPaused = false;
    let labelsVisible = true;
    let routesVisible = true;
    let fittedInitialNetwork = false;
    let airportsForMap = emptyFeatureCollection();

    const routeCache = new Map();
    const progressState = new Map();
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

    function setFeedMessage(message, { error = false, stale = false } = {}) {
        dom.feedMessage.textContent = message;
        dom.feedState.classList.toggle("is-error", error);
        dom.feedState.classList.toggle("is-stale", stale);
    }

    function authoritativeFeedMessage() {
        if (!latestPayload?.simulation?.active) {
            return "Simulation clock inactive · wall-time fallback";
        }
        return latestPayload.simulation.paused
            ? "Simulation clock paused"
            : `Live simulation · ${latestPayload.simulation.speed_multiplier}× speed`;
    }

    function currentSimulationMilliseconds(now = performance.now()) {
        if (!latestPayload) return null;
        return simulationTimeAt(
            latestPayload.simulation.time,
            latestPayload.simulation.speed_multiplier,
            receivedAt,
            now,
            latestPayload.simulation.paused,
        );
    }

    function renderClock(now = performance.now()) {
        const simulationMilliseconds = currentSimulationMilliseconds(now);
        if (!Number.isFinite(simulationMilliseconds)) return;
        const label = formatUtcDateTime(simulationMilliseconds);
        dom.simulationTime.textContent = label;
        dom.simulationTime.dateTime = new Date(simulationMilliseconds).toISOString();
        document.querySelectorAll("[data-server-time]").forEach((target) => {
            target.textContent = label;
            target.dateTime = new Date(simulationMilliseconds).toISOString();
        });
        if (selectedFlightNumber) dom.selected.simulation.textContent = label;
    }

    function renderUiState({ loading = false } = {}) {
        const state = deriveUiState({
            loading,
            hasPayload: latestPayload !== null,
            flightCount: flightState.flights.size,
            dataError,
            tileError,
            mapFatal,
        });
        dom.loading.hidden = !state.showLoading;
        dom.empty.hidden = !state.showEmpty;
        dom.fatal.hidden = !state.showFatal;
        dom.dataError.hidden = !state.showDataError;
        dom.tileError.hidden = !state.showTileError;
        root.classList.toggle("is-stale", state.stale);
    }

    function updateSummary(summary) {
        for (const [key, value] of Object.entries(summary ?? {})) {
            const target = root.querySelector(`[data-map-summary="${key}"]`);
            if (target) target.textContent = value;
        }
    }

    function createTextElement(tagName, className, text) {
        const element = document.createElement(tagName);
        if (className) element.className = className;
        element.textContent = text;
        return element;
    }

    function selectFlight(flightNumber, { focusPanel = false } = {}) {
        if (!flightState.flights.has(flightNumber)) return;
        selectedFlightNumber = flightNumber;
        updateFlightListSelection();
        renderSelectedFlight();
        renderMapFrame(performance.now(), true);
        if (focusPanel) dom.selectedPanel.focus?.();
    }

    function updateFlightListSelection() {
        for (const button of dom.activeList.querySelectorAll(".flight-index-select")) {
            const selected = button.dataset.flightNumber === selectedFlightNumber;
            button.setAttribute("aria-pressed", String(selected));
            button.closest("li")?.classList.toggle("is-selected", selected);
        }
    }

    function renderFlightList() {
        const fragment = document.createDocumentFragment();
        const flights = [...flightState.flights.values()].sort((left, right) =>
            left.flight_number.localeCompare(right.flight_number),
        );
        if (!flights.length) {
            fragment.append(
                createTextElement(
                    "li",
                    "active-flight-list-empty",
                    "No active simulated flights.",
                ),
            );
        }
        for (const flight of flights) {
            const item = document.createElement("li");
            if (flight.flight_number === selectedFlightNumber) item.classList.add("is-selected");
            const selectButton = document.createElement("button");
            selectButton.type = "button";
            selectButton.className = "flight-index-select";
            selectButton.dataset.flightNumber = flight.flight_number;
            selectButton.setAttribute(
                "aria-pressed",
                String(flight.flight_number === selectedFlightNumber),
            );
            selectButton.setAttribute(
                "aria-label",
                `Select ${flight.flight_number}, ${flight.origin.code} to ${flight.result_destination.code}`,
            );
            const identity = createTextElement("span", "flight-index-identity", "");
            identity.append(
                createTextElement("strong", "", flight.flight_number),
                createTextElement("small", "", flight.aircraft_registration),
            );
            const route = createTextElement(
                "span",
                "flight-index-route",
                `${flight.origin.code} → ${flight.result_destination.code}`,
            );
            const status = createTextElement(
                "span",
                `flight-index-status status-${flight.status_code}`,
                flight.status_label,
            );
            selectButton.append(identity, route, status);
            selectButton.addEventListener("click", () =>
                selectFlight(flight.flight_number),
            );
            const detailLink = createTextElement("a", "flight-index-link", "Open detail");
            detailLink.href = flight.flight_url;
            item.append(selectButton, detailLink);
            fragment.append(item);
        }
        dom.activeList.replaceChildren(fragment);
    }

    function renderSelectedFlight() {
        const flight = selectedFlightNumber
            ? flightState.flights.get(selectedFlightNumber)
            : null;
        dom.selectedEmpty.hidden = Boolean(flight);
        dom.selectedPanel.hidden = !flight;
        dom.clearButton.disabled = !flight;
        if (!flight) return;

        const progress = Math.round(
            (progressState.get(flight.flight_number) ?? flight.progress / 100) * 100,
        );
        dom.selected.status.textContent = flight.status_label;
        dom.selected.status.className = `status status--${flight.status_code}`;
        dom.selected.flightNumber.textContent = flight.flight_number;
        dom.selected.progress.textContent = `${progress}%`;
        dom.selected.aircraft.textContent =
            `${flight.aircraft_registration} · ${flight.aircraft_type}`;
        dom.selected.origin.textContent = `${flight.origin.code} · ${flight.origin.city}`;
        dom.selected.planned.textContent =
            `${flight.planned_destination.code} · ${flight.planned_destination.city}`;
        dom.selected.result.textContent =
            `${flight.result_destination.code} · ${flight.result_destination.city}`;
        dom.selected.resultRow.classList.toggle("is-diverted", flight.diverted);
        dom.selected.delay.textContent =
            flight.delay_minutes > 0 ? `+${flight.delay_minutes} min` : "On schedule";
        dom.selected.departure.textContent = formatUtcDateTime(flight.effective_departure);
        dom.selected.arrival.textContent = formatUtcDateTime(flight.effective_arrival);
        dom.selected.flightUrl.href = flight.flight_url;
        dom.selected.aircraftUrl.href = flight.aircraft_url;
    }

    function renderMapFrame(now = performance.now(), authoritativeOnly = false) {
        if (!latestPayload) return;
        const simulationMilliseconds = currentSimulationMilliseconds(now);
        if (!Number.isFinite(simulationMilliseconds)) return;
        const collections = buildMapCollections(
            flightState.flights,
            simulationMilliseconds,
            routeCache,
            progressState,
            { authoritativeOnly },
        );
        if (mapReady) {
            const selectedFlight = selectedFlightNumber
                ? flightState.flights.get(selectedFlightNumber)
                : null;
            updateMapSources(
                map,
                collections,
                airportsForMap,
                selectedRouteCollection(selectedFlight, routeCache),
            );
        }
        renderSelectedFlight();
        renderClock(now);
    }

    function cleanRuntimeCaches() {
        const liveFlightNumbers = new Set(flightState.flights.keys());
        for (const flightNumber of progressState.keys()) {
            if (!liveFlightNumbers.has(flightNumber)) progressState.delete(flightNumber);
        }
        const liveRouteKeys = new Set(
            [...flightState.flights.values()].map((flight) => flight.routeKey),
        );
        for (const key of routeCache.keys()) {
            if (!liveRouteKeys.has(key)) routeCache.delete(key);
        }
    }

    function applyPayload(payload, sequence) {
        const reconciled = reconcileFlightState(flightState, payload, sequence);
        if (!reconciled.accepted) return;
        flightState = reconciled;
        latestPayload = payload;
        receivedAt = performance.now();
        selectedFlightNumber = reconcileSelection(
            selectedFlightNumber,
            flightState.flights,
        );
        cleanRuntimeCaches();
        updateSummary(payload.summary);
        airportsForMap = mapReady
            ? prepareAirportLabels(map, payload.airports)
            : payload.airports;
        dataError = false;
        renderFlightList();
        renderUiState();
        renderMapFrame(receivedAt, true);

        if (mapReady && !fittedInitialNetwork && flightState.flights.size) {
            fitNetworkBounds(map, payload.bounds);
            fittedInitialNetwork = true;
        }
        if (payload.simulation.active) {
            setFeedMessage(authoritativeFeedMessage());
        } else {
            setFeedMessage("Simulation clock inactive · wall-time fallback", {
                error: true,
            });
        }
        startAnimation();
    }

    async function refreshNetwork() {
        if (document.hidden || !config) return;
        requestController?.abort();
        const controller = new AbortController();
        requestController = controller;
        const sequence = ++requestSequence;
        renderUiState({ loading: true });
        setFeedMessage("Refreshing authoritative state");
        try {
            const payload = await fetchNetworkState(config.dataUrl, {
                signal: controller.signal,
            });
            applyPayload(payload, sequence);
        } catch (error) {
            if (error.name === "AbortError") return;
            dataError = true;
            renderUiState();
            setFeedMessage("Flight feed unavailable · showing last valid state", {
                error: true,
                stale: latestPayload !== null,
            });
        } finally {
            if (requestController === controller) requestController = null;
        }
    }

    function stopAnimation() {
        if (animationFrame !== null) cancelAnimationFrame(animationFrame);
        animationFrame = null;
    }

    function animate(now) {
        if (
            !shouldAnimate({
                hidden: document.hidden,
                reducedMotion: reducedMotion.matches,
                clientPaused,
                serverPaused: latestPayload?.simulation?.paused,
                hasFlights: flightState.flights.size > 0,
            })
        ) {
            stopAnimation();
            return;
        }
        if (now - lastFrameAt >= 80) {
            lastFrameAt = now;
            renderMapFrame(now);
        }
        animationFrame = requestAnimationFrame(animate);
    }

    function startAnimation() {
        stopAnimation();
        if (
            shouldAnimate({
                hidden: document.hidden,
                reducedMotion: reducedMotion.matches,
                clientPaused,
                serverPaused: latestPayload?.simulation?.paused,
                hasFlights: flightState.flights.size > 0,
            })
        ) {
            animationFrame = requestAnimationFrame(animate);
        }
    }

    function startTimers() {
        if (pollTimer === null) pollTimer = window.setInterval(refreshNetwork, 15_000);
        if (clockTimer === null) clockTimer = window.setInterval(renderClock, 1_000);
    }

    function stopTimers() {
        if (pollTimer !== null) window.clearInterval(pollTimer);
        if (clockTimer !== null) window.clearInterval(clockTimer);
        pollTimer = null;
        clockTimer = null;
        requestController?.abort();
        requestController = null;
        stopAnimation();
    }

    function bindMapSelection() {
        for (const layerId of [
            LAYER_IDS.aircraftHalo,
            LAYER_IDS.routes,
            LAYER_IDS.completedRoutes,
        ]) {
            map.on("click", layerId, (event) => {
                const flightNumber = event.features?.[0]?.properties?.flight_number;
                if (flightNumber) selectFlight(flightNumber);
            });
            map.on("mouseenter", layerId, () => {
                map.getCanvas().style.cursor = "pointer";
            });
            map.on("mouseleave", layerId, () => {
                map.getCanvas().style.cursor = "";
            });
        }
    }

    async function initializeMap() {
        if (!config?.tileUrl || !config?.aircraftIconUrl) {
            mapFatal = true;
            renderUiState();
            setFeedMessage("Map configuration is unavailable", { error: true });
            return;
        }
        try {
            map = createNetworkMap(maplibregl, dom.map, config, () => {
                tileError = true;
                renderUiState();
            });
            await waitForMapLoad(map);
            await installOperationalLayers(map, config.aircraftIconUrl);
            mapReady = true;
            root.classList.add("is-map-ready");
            bindMapSelection();
            if (latestPayload) {
                airportsForMap = prepareAirportLabels(map, latestPayload.airports);
                renderMapFrame(performance.now(), true);
                if (latestPayload.bounds && flightState.flights.size) {
                    fitNetworkBounds(map, latestPayload.bounds);
                    fittedInitialNetwork = true;
                }
            }
        } catch {
            mapFatal = true;
            root.classList.add("is-map-fatal");
            renderUiState();
            setFeedMessage("Map rendering unavailable · flight index remains active", {
                error: true,
            });
        }
    }

    root.addEventListener("click", (event) => {
        const control = event.target.closest("[data-map-action]");
        if (!control) return;
        const action = control.dataset.mapAction;
        if (action === "fit") {
            if (mapReady) fitNetworkBounds(map, latestPayload?.bounds);
        } else if (action === "labels") {
            labelsVisible = !labelsVisible;
            control.setAttribute("aria-pressed", String(labelsVisible));
            if (mapReady) setLayerVisibility(map, [LAYER_IDS.labels], labelsVisible);
        } else if (action === "routes") {
            routesVisible = !routesVisible;
            control.setAttribute("aria-pressed", String(routesVisible));
            if (mapReady) {
                setLayerVisibility(
                    map,
                    [LAYER_IDS.routes, LAYER_IDS.completedRoutes, LAYER_IDS.selected],
                    routesVisible,
                );
            }
        } else if (action === "pause") {
            clientPaused = !clientPaused;
            control.setAttribute("aria-pressed", String(clientPaused));
            control.textContent = clientPaused
                ? "Resume visual motion"
                : "Pause visual motion";
            if (clientPaused) {
                stopAnimation();
                setFeedMessage("Visual motion paused · server clock continues");
            } else {
                renderMapFrame(performance.now());
                startAnimation();
                setFeedMessage(authoritativeFeedMessage());
            }
        } else if (action === "refresh") {
            refreshNetwork();
        } else if (action === "clear") {
            selectedFlightNumber = null;
            updateFlightListSelection();
            renderSelectedFlight();
            renderMapFrame(performance.now(), true);
        }
    });

    document.addEventListener("visibilitychange", () => {
        if (document.hidden) {
            stopTimers();
        } else {
            startTimers();
            refreshNetwork();
        }
    });
    reducedMotion.addEventListener("change", () => {
        renderMapFrame(performance.now(), true);
        startAnimation();
    });
    window.addEventListener(
        "pagehide",
        () => {
            stopTimers();
            map?.remove();
        },
        { once: true },
    );

    renderUiState({ loading: true });
    initializeMap();
    refreshNetwork();
    startTimers();
}
