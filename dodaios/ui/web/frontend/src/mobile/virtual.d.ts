/**
 * `virtual:mobile-strings` is built by the `mobileStrings` plugin in
 * vite.config.ts: the `mobile.app` namespace of every locale file, inlined.
 * The phone bundle must not import the locale JSON itself — that module is
 * part of the desktop entry, and a shared module would pull the desktop's
 * startup bundle apart into a common chunk.
 */
declare module "virtual:mobile-strings" {
  const strings: Record<string, Record<string, string>>;
  export default strings;
}
