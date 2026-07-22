# Map troubleshooting

The live map normally recovers without restarting Django. Renderer startup retries
twice, and a failed public basemap falls back to the local grid while tile recovery
runs independently of the flight feed.

If the map is still blank, collect one browser trace before restarting the server:

1. Open the browser developer tools (`F12`) and select **Console**. Enable **Preserve
   log**, clear the console, and reload `/network-map/` once.
2. Copy any red errors, especially entries containing `[network-map]`, `MapLibre`,
   `WebGL`, `network-map.js`, or `ERR_`.
3. Open **Network**, keep **Preserve log** enabled, and record the status shown for:
   the page document, `network-map.js`, `network-map.css`, `/network-map/data/`, and
   requests to `tile.openstreetmap.org`.
4. Send the copied errors, those response statuses, the browser name/version, and the
   approximate failure time. A screenshot of the map warning is also useful.

If you export a HAR file, remove cookies, authorization headers, and sensitive query
values before sharing it. Tile failures with a working data endpoint point to the
public raster service or browser/network policy; a missing canvas or a
`[network-map] MapLibre initialization failed` error points to renderer startup.
