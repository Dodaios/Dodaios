import fs from "node:fs";
import path from "node:path";
import type { Plugin } from "vite";

/** Where the whiteboard editor finds its fonts; `window.EXCALIDRAW_ASSET_PATH` names it. */
export const WHITEBOARD_ASSET_ROUTE = "/assets/excalidraw";

/**
 * The editor package falls back to a public CDN when a font cannot be loaded
 * from the asset path it was given. The app runs offline and must not reach
 * the web on its own, so the fallback is pointed at a path of this app that
 * does not exist: a missing font then stays missing instead of being fetched.
 */
const CDN_FALLBACK = "https://esm.sh/";
const LOCAL_FALLBACK = `\${window.location.origin}${WHITEBOARD_ASSET_ROUTE}/no-fallback/`;

const FONT_FILE = /^[a-zA-Z0-9_-]+\/[a-zA-Z0-9_.-]+\.woff2$/;

/**
 * Self-host the whiteboard editor's runtime assets.
 *
 * The editor draws text in its own fonts and loads them by URL at run time
 * (only the UI font comes through its stylesheet, which Vite bundles itself).
 * Development serves the pinned package's font folder directly; production
 * copies it beside the static assets, so the desktop app never asks a CDN.
 */
export function whiteboardAssets(root: string): Plugin {
  const fontSource = path.resolve(root, "node_modules/@excalidraw/excalidraw/dist/prod/fonts");
  let outputDirectory = "";
  let rewrote = 0;

  return {
    name: "whiteboard-assets",
    configResolved(config) {
      outputDirectory = path.resolve(config.root, config.build.outDir);
    },
    configureServer(server) {
      server.middlewares.use(`${WHITEBOARD_ASSET_ROUTE}/fonts`, (request, response, next) => {
        let requested = "";
        try {
          requested = decodeURIComponent(request.url ?? "").split("?", 1)[0].replace(/^\/+/, "");
        } catch {
          next();
          return;
        }
        if (!FONT_FILE.test(requested)) {
          next();
          return;
        }
        const file = path.resolve(fontSource, requested);
        if (!file.startsWith(fontSource + path.sep) || !fs.existsSync(file)) {
          next();
          return;
        }
        response.setHeader("Content-Type", "font/woff2");
        response.setHeader("Cache-Control", "public, max-age=3600");
        fs.createReadStream(file).pipe(response);
      });
    },
    buildStart() {
      rewrote = 0;
    },
    transform(code, id) {
      if (!id.includes("/@excalidraw/excalidraw/dist/") || !code.includes("ASSETS_FALLBACK_URL")) {
        return null;
      }
      const count = code.split(CDN_FALLBACK).length - 1;
      // The replacement reads the page's origin, so it must land at the start
      // of a template literal, which is where the package keeps the fallback.
      if (count !== 1 || !code.includes("`" + CDN_FALLBACK)) {
        // A new package version moved the fallback: look at it again rather
        // than ship a build that may load fonts from the web.
        this.error(`whiteboard-assets: expected one CDN font fallback in ${id}, found ${count}`);
      }
      rewrote += 1;
      return { code: code.replace(CDN_FALLBACK, LOCAL_FALLBACK), map: null };
    },
    writeBundle() {
      if (rewrote === 0) {
        this.error("whiteboard-assets: the editor's CDN font fallback was not found in the bundle");
      }
      fs.cpSync(fontSource, path.join(outputDirectory, "assets", "excalidraw", "fonts"), { recursive: true });
    },
  };
}
