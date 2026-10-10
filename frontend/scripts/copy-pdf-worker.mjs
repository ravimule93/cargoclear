// Copies the pdf.js worker out of node_modules into public/ so it is served at
// /pdf.worker.min.mjs. The worker version must match the pdfjs-dist library, so we
// always copy from the installed package instead of committing a snapshot.
//
// This script must never fail `npm install`: every problem is reported as a warning.
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const buildDir = join(root, "node_modules", "pdfjs-dist", "build");
const destDir = join(root, "public");
const dest = join(destDir, "pdf.worker.min.mjs");

// pdfjs-dist 4.10.x ships both names; older 4.x only shipped pdf.worker.mjs.
const candidates = ["pdf.worker.min.mjs", "pdf.worker.mjs"];

try {
  const source = candidates.map((name) => join(buildDir, name)).find((p) => existsSync(p));
  if (!source) {
    console.warn(`[copy-pdf-worker] no pdf.js worker found in ${buildDir}; skipping`);
  } else {
    mkdirSync(destDir, { recursive: true });
    copyFileSync(source, dest);
    console.log(`[copy-pdf-worker] ${source} -> ${dest}`);
  }
} catch (err) {
  console.warn(`[copy-pdf-worker] could not copy worker: ${err instanceof Error ? err.message : err}`);
}
process.exit(0);
