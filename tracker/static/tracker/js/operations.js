(() => {
    "use strict";

    const deviceClock = document.querySelector("[data-device-clock]");
    const deviceFormatter = new Intl.DateTimeFormat(undefined, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
        timeZoneName: "short",
    });

    function updateDeviceClock() {
        if (deviceClock) {
            deviceClock.textContent = deviceFormatter.format(new Date());
            deviceClock.dateTime = new Date().toISOString();
        }
    }

    updateDeviceClock();
    window.setInterval(updateDeviceClock, 1000);

    const board = document.querySelector("[data-board]");
    if (!board) return;

    const rows = board.querySelector("[data-flight-rows]");
    const refreshState = board.querySelector("[data-refresh-status]");
    let activeController = null;
    let pollTimer = null;
    let requestSequence = 0;
    let appliedSequence = 0;

    function endpointUrl() {
        const url = new URL(board.dataset.endpoint, window.location.origin);
        url.search = window.location.search;
        return url;
    }

    async function refreshBoard() {
        if (document.hidden) return;
        activeController?.abort();
        const controller = new AbortController();
        activeController = controller;
        const sequence = ++requestSequence;
        board.setAttribute("aria-busy", "true");
        try {
            const response = await fetch(endpointUrl(), {
                headers: { Accept: "application/json" },
                cache: "no-store",
                signal: controller.signal,
            });
            if (!response.ok) throw new Error(`Board request failed: ${response.status}`);
            const payload = await response.json();
            if (sequence < requestSequence || sequence <= appliedSequence) return;
            appliedSequence = sequence;
            const focusedHref = rows.contains(document.activeElement)
                ? document.activeElement.getAttribute("href")
                : null;
            rows.innerHTML = payload.html;
            if (focusedHref) {
                rows.querySelector(`a[href="${CSS.escape(focusedHref)}"]`)?.focus();
            }
            Object.entries(payload.summary).forEach(([key, value]) => {
                const target = board.querySelector(`[data-summary="${key}"]`);
                if (target) target.textContent = value;
            });
            document.querySelectorAll("[data-server-time]").forEach((target) => {
                target.textContent = payload.simulation_time_label;
                target.dateTime = payload.simulation_time;
            });
            refreshState.textContent = `Updated ${payload.generated_at_label}`;
            refreshState.parentElement.classList.remove("is-error");
        } catch (error) {
            if (error.name === "AbortError") return;
            refreshState.textContent = "Live update unavailable · showing last server response";
            refreshState.parentElement.classList.add("is-error");
        } finally {
            if (activeController === controller) {
                activeController = null;
                board.setAttribute("aria-busy", "false");
            }
        }
    }

    function startPolling() {
        if (pollTimer === null) pollTimer = window.setInterval(refreshBoard, 20_000);
    }

    function stopPolling() {
        if (pollTimer !== null) window.clearInterval(pollTimer);
        pollTimer = null;
        activeController?.abort();
        activeController = null;
        board.setAttribute("aria-busy", "false");
    }

    startPolling();
    document.addEventListener("visibilitychange", () => {
        if (document.hidden) {
            stopPolling();
        } else {
            startPolling();
            refreshBoard();
        }
    });
    window.addEventListener("pagehide", stopPolling, { once: true });
})();
