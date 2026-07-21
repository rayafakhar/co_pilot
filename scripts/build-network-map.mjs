import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

import { build } from "esbuild";

const outputBase = resolve("tracker/static/tracker/dist/network-map");

await build({
    entryPoints: ["tracker/assets/network-map/app.js"],
    bundle: true,
    format: "iife",
    target: "es2020",
    minify: true,
    outfile: `${outputBase}.js`,
});

// MapLibre includes shader source strings with line-ending spaces. Removing those
// spaces is semantics-neutral and keeps the committed generated files diff-check clean.
for (const extension of ["js", "css"]) {
    const outputPath = `${outputBase}.${extension}`;
    const contents = await readFile(outputPath, "utf8");
    await writeFile(outputPath, contents.replace(/[ \t]+$/gm, ""), "utf8");
}
