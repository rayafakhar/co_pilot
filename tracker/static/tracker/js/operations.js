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
    let polling = false;

    function endpointUrl() {
        const url = new URL(board.dataset.endpoint, window.location.origin);
        url.search = window.location.search;
        return url;
    }

    async function refreshBoard() {
        if (polling || document.hidden) return;
        polling = true;
        try {
            const response = await fetch(endpointUrl(), {
                headers: { Accept: "application/json" },
                cache: "no-store",
            });
            if (!response.ok) throw new Error(`Board request failed: ${response.status}`);
            const payload = await response.json();
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
                target.textContent = payload.generated_at_label;
                target.dateTime = payload.generated_at;
            });
            refreshState.textContent = `Updated ${payload.generated_at_label}`;
            refreshState.parentElement.classList.remove("is-error");
        } catch (error) {
            refreshState.textContent = "Live update unavailable · showing last server response";
            refreshState.parentElement.classList.add("is-error");
        } finally {
            polling = false;
        }
    }

    window.setInterval(refreshBoard, 20_000);
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) refreshBoard();
    });
})();
