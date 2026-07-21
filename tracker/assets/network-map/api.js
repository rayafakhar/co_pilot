export async function fetchNetworkState(url, { signal, fetchImpl = fetch } = {}) {
    const response = await fetchImpl(url, {
        headers: { Accept: "application/json" },
        cache: "no-store",
        signal,
    });
    if (!response.ok) {
        throw new Error(`Network map request failed: ${response.status}`);
    }
    const payload = await response.json();
    if (payload?.schema_version !== 1 || !Array.isArray(payload.flights)) {
        throw new Error("Network map response has an unsupported schema.");
    }
    return payload;
}
