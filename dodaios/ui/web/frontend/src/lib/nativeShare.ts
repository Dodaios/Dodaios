/**
 * The macOS share sheet, reached from the desktop WebView.
 *
 * The desktop shell registers `window.webkit.messageHandlers.jarvisShare`
 * (`dodaios/ui/native_share.py`); a message naming a staged file opens
 * `NSSharingServicePicker` beside the rectangle it names — AirDrop, Mail,
 * Messages and every share extension the person installed. The handler only
 * accepts files the backend staged for sharing, so a page cannot put any
 * other file of the person's into the sheet.
 *
 * `canNativeShare()` is false in a plain browser, on Windows and Linux, and on
 * a headless server; the Artifacts stage downloads the staged file there.
 */

/** Discriminator — MUST match `MESSAGE_TAG` in dodaios/ui/native_share.py. */
const SHARE_MESSAGE_TAG = "jarvis-share";
/** Handler name — MUST match `MACOS_MESSAGE_HANDLER` in native_share.py. */
const MACOS_MESSAGE_HANDLER = "jarvisShare";

interface NativeMessageBridge {
  postMessage: (message: unknown) => void;
}

function bridge(): NativeMessageBridge | undefined {
  const host = window as unknown as {
    webkit?: { messageHandlers?: Record<string, NativeMessageBridge | undefined> };
  };
  const handler = host.webkit?.messageHandlers?.[MACOS_MESSAGE_HANDLER];
  return handler && typeof handler.postMessage === "function" ? handler : undefined;
}

/** True in the macOS desktop window, where the share sheet is available. */
export function canNativeShare(): boolean {
  return bridge() !== undefined;
}

/** Where the sheet should point: the button that was pressed, in CSS pixels. */
export interface ShareAnchor {
  x: number;
  y: number;
  width: number;
  height: number;
}

export function anchorOf(element: Element | null): ShareAnchor {
  if (!element) return { x: 0, y: 0, width: 1, height: 1 };
  const box = element.getBoundingClientRect();
  return { x: box.left, y: box.top, width: box.width, height: box.height };
}

/** Open the share sheet for staged files. False outside the desktop window. */
export function shareFilesNatively(paths: string[], anchor: ShareAnchor): boolean {
  const nativeBridge = bridge();
  if (!nativeBridge || paths.length === 0) return false;
  nativeBridge.postMessage([SHARE_MESSAGE_TAG, { files: paths, rect: anchor }]);
  return true;
}
