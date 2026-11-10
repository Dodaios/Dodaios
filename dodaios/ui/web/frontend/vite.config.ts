/// <reference types="vitest/config" />
import fs from "node:fs";
import { defineConfig } from "vite";
import type { Plugin } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

import { missingNameGate } from "./vite-plugins/missingNameGate";
import { safePublication } from "./vite-plugins/safePublication";
import { thirdPartyNotices } from "./vite-plugins/thirdPartyNotices";

const notices = thirdPartyNotices(__dirname);

const MATERIAL_ICON_ROUTE = "/assets/material-file-icons";
const materialIconSource = path.resolve(
  __dirname,
  "node_modules/material-icon-theme/icons",
);

/**
 * Keep the complete icon theme out of the Agentic IDE JavaScript chunk.
 * Development serves the pinned package directly; production copies the same
 * MIT-licensed SVGs beside the static assets for offline desktop use.
 */
function materialIconAssets(): Plugin {
  let outputDirectory = "";

  return {
    name: "material-file-icon-assets",
    configResolved(config) {
      outputDirectory = path.resolve(config.root, config.build.outDir);
    },
    configureServer(server) {
      server.middlewares.use(MATERIAL_ICON_ROUTE, (request, response, next) => {
        let requestedFile = "";
        try {
          requestedFile = decodeURIComponent(request.url ?? "")
            .split("?", 1)[0]
            .replace(/^\/+/, "");
        } catch {
          next();
          return;
        }
        if (!/^[a-zA-Z0-9_.-]+\.svg$/.test(requestedFile)) {
          next();
          return;
        }

        const sourceFile = path.resolve(materialIconSource, requestedFile);
        if (
          path.dirname(sourceFile) !== materialIconSource ||
          !fs.existsSync(sourceFile)
        ) {
          next();
          return;
        }

        response.setHeader("Content-Type", "image/svg+xml");
        response.setHeader("Cache-Control", "public, max-age=3600");
        fs.createReadStream(sourceFile).pipe(response);
      });
    },
    writeBundle() {
      fs.cpSync(
        materialIconSource,
        path.join(outputDirectory, "assets", "material-file-icons"),
        { recursive: true },
      );
    },
  };
}

const MOBILE_STRINGS_ID = "virtual:mobile-strings";
const MOBILE_LANGUAGES = ["en", "de", "es", "pt", "zh"] as const;

/**
 * The phone companion's strings, inlined from the `mobile.app` namespace of
 * every locale file. The phone bundle must share NO module with the desktop
 * entry (a shared module becomes a common chunk and changes how the desktop
 * starts), so it cannot import the locale JSON; this hands it the one
 * namespace it needs instead.
 */
function mobileStrings(): Plugin {
  const resolved = "\0" + MOBILE_STRINGS_ID;
  const localeFile = (lang: string) => path.resolve(__dirname, `src/i18n/locales/${lang}.json`);
  return {
    name: "mobile-strings",
    resolveId(source) {
      return source === MOBILE_STRINGS_ID ? resolved : undefined;
    },
    load(id) {
      if (id !== resolved) return undefined;
      const out: Record<string, unknown> = {};
      for (const lang of MOBILE_LANGUAGES) {
        this.addWatchFile(localeFile(lang));
        const tree = JSON.parse(fs.readFileSync(localeFile(lang), "utf8")) as {
          mobile?: { app?: Record<string, string> };
        };
        out[lang] = tree.mobile?.app ?? {};
      }
      return `export default ${JSON.stringify(out)};`;
    },
  };
}

export default defineConfig({
  plugins: [safePublication(__dirname), react(), materialIconAssets(), missingNameGate(__dirname), notices.plugin, mobileStrings()],
  worker: { plugins: () => [notices.workerPlugin()] },
  // The society's figures are binary glTF; Vite serves them as fingerprinted
  // assets (docs/agent-society/character-pipeline.md §4.2).
  assetsInclude: ["**/*.glb"],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:47821",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://127.0.0.1:47821",
        ws: true,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "../dist",
    emptyOutDir: true,
    // Two documents: the desktop app and the phone companion (dist/m/index.html,
    // served at /m/). The phone entry imports nothing the desktop entry does,
    // so the desktop's startup chunk is unchanged by its presence.
    rollupOptions: {
      input: {
        index: path.resolve(__dirname, "index.html"),
        mobile: path.resolve(__dirname, "m/index.html"),
      },
    },
    // No source maps in production builds. They bloat the bundle, expose the
    // full original source, and bake the absolute build path (e.g. a personal
    // C:\Users\... home dir) into the .map files — none of which belongs in the
    // prebuilt dist shipped to the public repo. The Vite dev server keeps its
    // own inline maps, so local debugging is unaffected.
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
});
