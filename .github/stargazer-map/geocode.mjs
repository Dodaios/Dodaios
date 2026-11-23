#!/usr/bin/env node
/**
 * Turn a GitHub profile's location line into a point on the globe.
 *
 * The input is whatever the person felt like typing. There is no format to
 * parse, so this is a matcher, not a parser, and its most important property
 * is that it is allowed to give up. A marker in the wrong hemisphere is worse
 * than no marker, so an unresolved location is counted and dropped, never
 * guessed at.
 *
 * The order of attempts, and why:
 *
 *   1. A curated alias, whole-string. "SF Bay Area" is one place, not three
 *      comma-separated ones, and no gazetteer contains it.
 *   2. A country hint from ANY comma part. "Calgary, AB, Canada" and
 *      "USA, Minnesota" put the country at opposite ends.
 *   3. A city, preferring one inside the hinted country. This is what saves
 *      the US state codes: "Boston, MA" hints Morocco, finds no Boston there,
 *      and falls through to the Boston that has four million people.
 *   4. A region (state, province, Bundesland), positioned on its largest city
 *      but labelled as the region — "Minnesota, United States", not
 *      "Minneapolis".
 *   5. The country alone.
 *
 * Build-only. Nothing here ships to the browser.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));

/**
 * Fold a location string down to something comparable.
 *
 * Diacritics go (so "München" meets "Munchen"), emoji and flags go (a lot of
 * people decorate their location with one), and every separator people use
 * between a city and a country — comma, slash, pipe, dash, bullet — becomes a
 * comma so the split below has one thing to look for.
 *
 * Scripts other than Latin are deliberately left alone: "Россия" normalises to
 * itself and matches the Russian name Natural Earth ships.
 */
export function normalise(value) {
  if (value == null) return "";
  return String(value)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    // Emoji, flags, pictographs, arrows, box drawing.
    .replace(/[\u{1F000}-\u{1FAFF}\u{2190}-\u{2BFF}\u{FE00}-\u{FE0F}\u{2600}-\u{27BF}]/gu, " ")
    .toLowerCase()
    .replace(/[\\/|·•;:]+/g, ",")
    .replace(/[^\p{L}\p{N},.\-' ]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Split a normalised line into its comma-separated parts. */
function parts(value) {
  return value
    .split(",")
    .map((p) => p.replace(/^[\s.'-]+|[\s.'-]+$/g, "").trim())
    .filter((p) => p.length >= 2);
}

/**
 * Strings people put in the location field that are not locations.
 *
 * Left as a list rather than a heuristic because there is no heuristic: the
 * only thing "Planet Telex" and "/dev/null" have in common is that a human
 * reading them knows better. Anything not listed simply fails to match and is
 * counted as unplaced, so the list is a nicety — it keeps the build log
 * honest about what was rejected on purpose.
 */
const NOT_A_PLACE = new Set([
  "remote", "remote first", "worldwide", "world wide", "the world", "world",
  "earth", "planet earth", "somewhere on earth", "everywhere", "anywhere",
  "internet", "the internet", "online", "web", "cyberspace", "localhost",
  "dev null", "home", "somewhere", "here", "there", "n a", "na", "unknown",
  "nowhere", "mars", "moon", "space", "the metaverse", "metaverse",
  "your terminal", "in your walls", "planet telex", "127.0.0.1", "0.0.0.0",
]);

/**
 * The names a gazetteer of formal place names does not have.
 *
 * Three kinds live here: nicknames ("Frisco"), renamed cities people still use
 * the old name for ("Bombay"), and towns too small for a 7 000-city dataset
 * but thick with developers ("Mountain View"). Each entry is a place, so each
 * carries its own point and its own label.
 */
const ALIASES = [
  // — San Francisco Bay Area ————————————————————————————————
  { keys: ["sf", "s f", "san fran", "frisco", "san francisco bay area", "sf bay area", "bay area", "the bay", "sfba"], label: "San Francisco", country: "United States of America", lat: 37.775, lon: -122.419 },
  { keys: ["silicon valley", "san jose ca", "svl"], label: "San Jose", country: "United States of America", lat: 37.339, lon: -121.895 },
  { keys: ["mountain view"], label: "Mountain View", country: "United States of America", lat: 37.386, lon: -122.084 },
  { keys: ["palo alto"], label: "Palo Alto", country: "United States of America", lat: 37.442, lon: -122.143 },
  { keys: ["cupertino"], label: "Cupertino", country: "United States of America", lat: 37.323, lon: -122.032 },
  { keys: ["menlo park"], label: "Menlo Park", country: "United States of America", lat: 37.454, lon: -122.182 },
  { keys: ["sunnyvale"], label: "Sunnyvale", country: "United States of America", lat: 37.369, lon: -122.036 },
  { keys: ["berkeley"], label: "Berkeley", country: "United States of America", lat: 37.872, lon: -122.271 },
  { keys: ["redwood city"], label: "Redwood City", country: "United States of America", lat: 37.485, lon: -122.236 },
  // — other US ————————————————————————————————————————————
  { keys: ["nyc", "new york city", "ny", "ny ny", "brooklyn", "manhattan", "queens ny", "the bronx", "new york ny"], label: "New York", country: "United States of America", lat: 40.713, lon: -74.006 },
  { keys: ["la", "socal", "southern california", "los angeles ca"], label: "Los Angeles", country: "United States of America", lat: 34.052, lon: -118.244 },
  { keys: ["dc", "washington dc", "washington d c"], label: "Washington, D.C.", country: "United States of America", lat: 38.895, lon: -77.037 },
  { keys: ["cambridge ma"], label: "Cambridge, MA", country: "United States of America", lat: 42.373, lon: -71.11 },
  { keys: ["ann arbor"], label: "Ann Arbor", country: "United States of America", lat: 42.281, lon: -83.743 },
  { keys: ["boulder"], label: "Boulder", country: "United States of America", lat: 40.015, lon: -105.271 },
  { keys: ["pnw", "pacific northwest"], label: "Seattle", country: "United States of America", lat: 47.606, lon: -122.332 },
  // — renamed, or transliterated another way ————————————————
  { keys: ["bangalore", "blr", "bengaluru india"], label: "Bengaluru", country: "India", lat: 12.972, lon: 77.594 },
  { keys: ["bombay"], label: "Mumbai", country: "India", lat: 19.076, lon: 72.878 },
  { keys: ["calcutta"], label: "Kolkata", country: "India", lat: 22.573, lon: 88.364 },
  { keys: ["madras"], label: "Chennai", country: "India", lat: 13.083, lon: 80.271 },
  { keys: ["ncr", "delhi ncr", "gurgaon", "gurugram", "noida"], label: "Delhi", country: "India", lat: 28.614, lon: 77.209 },
  { keys: ["saigon", "hcmc", "ho chi minh", "ho chi minh city"], label: "Ho Chi Minh City", country: "Vietnam", lat: 10.823, lon: 106.63 },
  { keys: ["peking"], label: "Beijing", country: "China", lat: 39.905, lon: 116.391 },
  { keys: ["gothenburg", "goteborg"], label: "Göteborg", country: "Sweden", lat: 57.708, lon: 11.974 },
  { keys: ["muenchen", "munchen"], label: "München", country: "Germany", lat: 48.137, lon: 11.575 },
  { keys: ["koln", "koeln", "cologne"], label: "Köln", country: "Germany", lat: 50.938, lon: 6.96 },
  { keys: ["nurnberg", "nuernberg", "nuremberg"], label: "Nürnberg", country: "Germany", lat: 49.452, lon: 11.077 },
  { keys: ["den haag", "the hague"], label: "Den Haag", country: "Netherlands", lat: 52.078, lon: 4.288 },
  { keys: ["kiev"], label: "Kyiv", country: "Ukraine", lat: 50.45, lon: 30.523 },
  { keys: ["constantinople", "istanbul turkiye"], label: "İstanbul", country: "Turkey", lat: 41.008, lon: 28.978 },
  // — written in the local script ————————————————————————————
  // Natural Earth carries city names in Latin only, so a location typed in
  // Cyrillic, Chinese, Japanese or Korean finds no city and falls through to
  // the country — which for Russia or China means a marker a thousand miles
  // from the person. The handful of cities big enough for that to be a common
  // outcome are listed by hand; the rest keep the country fallback, which is
  // coarse but never wrong.
  { keys: ["moskva", "москва"], label: "Moscow", country: "Russia", lat: 55.752, lon: 37.616 },
  { keys: ["санкт-петербург", "спб", "sankt peterburg"], label: "Saint Petersburg", country: "Russia", lat: 59.939, lon: 30.316 },
  { keys: ["київ", "киев"], label: "Kyiv", country: "Ukraine", lat: 50.45, lon: 30.523 },
  { keys: ["北京", "北京市"], label: "Beijing", country: "China", lat: 39.905, lon: 116.391 },
  { keys: ["上海", "上海市"], label: "Shanghai", country: "China", lat: 31.23, lon: 121.474 },
  { keys: ["深圳", "深圳市"], label: "Shenzhen", country: "China", lat: 22.543, lon: 114.058 },
  { keys: ["杭州", "杭州市"], label: "Hangzhou", country: "China", lat: 30.274, lon: 120.155 },
  { keys: ["广州", "廣州"], label: "Guangzhou", country: "China", lat: 23.129, lon: 113.264 },
  { keys: ["成都"], label: "Chengdu", country: "China", lat: 30.572, lon: 104.067 },
  { keys: ["東京", "东京", "東京都", "とうきょう"], label: "Tokyo", country: "Japan", lat: 35.689, lon: 139.692 },
  { keys: ["大阪"], label: "Osaka", country: "Japan", lat: 34.694, lon: 135.502 },
  { keys: ["서울", "ソウル"], label: "Seoul", country: "South Korea", lat: 37.567, lon: 126.978 },
  { keys: ["台北"], label: "Taipei", country: "Taiwan", lat: 25.033, lon: 121.565 },
  // — regions people name instead of a city ————————————————
  { keys: ["england"], label: "England", country: "United Kingdom", lat: 52.36, lon: -1.17 },
  { keys: ["scotland"], label: "Scotland", country: "United Kingdom", lat: 56.49, lon: -4.2 },
  { keys: ["wales"], label: "Wales", country: "United Kingdom", lat: 52.13, lon: -3.78 },
  { keys: ["northern ireland"], label: "Northern Ireland", country: "United Kingdom", lat: 54.61, lon: -6.63 },
  { keys: ["europe", "eu", "european union"], label: "Europe", country: "", lat: 50.0, lon: 15.0 },
  { keys: ["asia"], label: "Asia", country: "", lat: 34.0, lon: 100.0 },
  { keys: ["africa"], label: "Africa", country: "", lat: 2.0, lon: 21.0 },
  { keys: ["south america", "latin america", "latam"], label: "South America", country: "", lat: -14.0, lon: -58.0 },
  { keys: ["north america"], label: "North America", country: "", lat: 45.0, lon: -100.0 },
  { keys: ["oceania"], label: "Oceania", country: "", lat: -25.0, lon: 140.0 },
  { keys: ["middle east"], label: "Middle East", country: "", lat: 29.0, lon: 45.0 },
];

let cache = null;

function gazetteer() {
  if (cache) return cache;
  const raw = JSON.parse(readFileSync(join(HERE, "gazetteer.json"), "utf8"));

  // The file stores rows, not objects — see build-gazetteer.mjs for why. The
  // column order is named in the file itself and unpacked here, once.
  const countries = raw.countries.map(([name, a3, lat, lon, aliases]) => ({
    name, a3, lat, lon, aliases,
  }));
  const byA3 = new Map(countries.map((c) => [c.a3, c]));
  const cities = raw.cities.map(([label, a3, adm1, lat, lon, pop, names]) => ({
    label, a3, adm1, lat, lon, pop, names,
    country: byA3.get(a3)?.name ?? "",
  }));

  const countryByAlias = new Map();
  for (const c of countries) {
    for (const alias of c.aliases) {
      if (!countryByAlias.has(alias)) countryByAlias.set(alias, c);
    }
  }

  // Cities arrive population-descending, so the first entry under a name is
  // the biggest one wearing it — the right default for a bare "Cambridge".
  const cityByName = new Map();
  for (const city of cities) {
    for (const name of city.names) {
      if (!cityByName.has(name)) cityByName.set(name, []);
      cityByName.get(name).push(city);
    }
  }

  // A region is positioned on its largest city. Regions are not otherwise in
  // the data, and a state centroid would need a second dataset for something
  // three pixels wide on the finished globe.
  const regionByName = new Map();
  for (const city of cities) {
    if (!city.adm1) continue;
    const key = normalise(city.adm1);
    if (!key || regionByName.has(key)) continue;
    regionByName.set(key, city);
  }

  const aliasByKey = new Map();
  for (const entry of ALIASES) {
    for (const key of entry.keys) aliasByKey.set(key, entry);
  }

  cache = { countryByAlias, cityByName, regionByName, aliasByKey };
  return cache;
}

/**
 * @param {string} raw a GitHub profile's location line
 * @returns {{lat:number, lon:number, label:string, country:string, kind:string}|null}
 */
export function geocode(raw) {
  const line = normalise(raw);
  if (!line) return null;
  if (NOT_A_PLACE.has(line)) return null;

  const g = gazetteer();
  const segments = parts(line);
  if (segments.length === 0) return null;
  if (segments.every((s) => NOT_A_PLACE.has(s))) return null;

  // 1 — a curated alias: the whole line, the line with its commas rubbed out,
  // then any single segment. The middle one is what catches "Cambridge, MA"
  // and "Washington, DC" — one place that people write with a comma in it,
  // and that a split on commas would otherwise tear into a city in England
  // and a country code for Morocco.
  for (const key of [line, line.replace(/,\s*/g, " "), ...segments]) {
    const hit = g.aliasByKey.get(key);
    if (hit) return { ...pick(hit), kind: "alias" };
  }

  // 2 — a country named anywhere in the line.
  let country = null;
  for (const segment of segments) {
    const hit = g.countryByAlias.get(segment);
    if (hit) {
      country = hit;
      break;
    }
  }

  // 3 — a city, inside that country if we can.
  let loose = null;
  for (const segment of segments) {
    const candidates = g.cityByName.get(segment);
    if (!candidates) continue;
    if (country) {
      const inCountry = candidates.find((c) => c.a3 === country.a3);
      if (inCountry) return city(inCountry);
    }
    if (!loose) loose = candidates[0];
  }
  if (loose) return city(loose);

  // 4 — a region, positioned on its largest city and labelled as the region.
  for (const segment of segments) {
    const seat = g.regionByName.get(segment);
    if (!seat) continue;
    if (country && seat.a3 !== country.a3) continue;
    return {
      lat: seat.lat,
      lon: seat.lon,
      label: seat.adm1,
      country: seat.country,
      kind: "region",
    };
  }

  // 5 — the country on its own.
  if (country) {
    return {
      lat: country.lat,
      lon: country.lon,
      label: country.name,
      country: country.name,
      kind: "country",
    };
  }

  return null;
}

function pick(entry) {
  return { lat: entry.lat, lon: entry.lon, label: entry.label, country: entry.country };
}

function city(c) {
  return { lat: c.lat, lon: c.lon, label: c.label, country: c.country, kind: "city" };
}
