/**
 * The node editors keep their words in a locale chunk that the editor host
 * loads before it draws an editor. Tests render editors on their own, so the
 * chunk is made resident before every test file.
 */
import { beforeAll } from "vitest";

import { loadLocaleChunk } from "@/i18n";

beforeAll(async () => {
  await loadLocaleChunk("node_editors");
});
