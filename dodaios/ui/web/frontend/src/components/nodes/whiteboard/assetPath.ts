/**
 * Where the whiteboard editor loads its fonts from: this app, never a CDN.
 *
 * The package reads `window.EXCALIDRAW_ASSET_PATH` when it builds a font's
 * URL, so this module is imported before the package in the editor's chunk.
 * The build copies the fonts to this path and the dev server serves them
 * there (`vite-plugins/whiteboardAssets.ts`, `WHITEBOARD_ASSET_ROUTE`).
 */
declare global {
  interface Window {
    EXCALIDRAW_ASSET_PATH?: string | string[];
  }
}

export const WHITEBOARD_ASSET_PATH = "/assets/excalidraw/";

window.EXCALIDRAW_ASSET_PATH = WHITEBOARD_ASSET_PATH;
