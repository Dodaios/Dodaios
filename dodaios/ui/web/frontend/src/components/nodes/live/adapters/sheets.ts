/**
 * How a sheet is revealed while an agent builds it.
 *
 * The default reveal until this type's own lands: replace `defaultReveal`
 * with an adapter that returns this type's steps (docs/node-live-build.md,
 * "Writing a type's reveal"). Only this file and the sheets editor need to change.
 */
import { defaultReveal, type RevealAdapter } from "../reveal";

export const sheetsReveal: RevealAdapter = defaultReveal;
