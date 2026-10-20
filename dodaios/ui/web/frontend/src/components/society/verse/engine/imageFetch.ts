/**
 * Plate images: fetch → bytes → validated → ImageBitmap.
 *
 * The desktop app's server may label an .avif oddly and answers a missing
 * file with the app's index.html, so the MIME type is not trusted: the bytes
 * are sniffed, and anything that is not an image is an error, never a texture.
 * Decoding happens off the main thread in createImageBitmap, without colour
 * conversion, so the plate's sRGB values reach the GPU exactly as cooked.
 */

export type ImageType = "image/avif" | "image/png" | "image/jpeg" | "image/webp";

function ascii(bytes: Uint8Array, from: number, length: number): string {
  let s = "";
  for (let i = from; i < from + length && i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return s;
}

/** The image type the bytes really are, or null. Pure. */
export function sniffImage(bytes: Uint8Array): ImageType | null {
  if (bytes.length < 12) return null;
  if (ascii(bytes, 4, 4) === "ftyp") {
    const brand = ascii(bytes, 8, 4);
    if (brand === "avif" || brand === "avis") return "image/avif";
    // Some encoders write a generic brand first and list avif among the compatible ones.
    const box = (bytes[0] << 24) | (bytes[1] << 16) | (bytes[2] << 8) | bytes[3];
    for (let i = 16; i + 4 <= Math.min(box, 64); i += 4) {
      const compatible = ascii(bytes, i, 4);
      if (compatible === "avif" || compatible === "avis") return "image/avif";
    }
    return null;
  }
  if (bytes[0] === 0x89 && ascii(bytes, 1, 3) === "PNG") return "image/png";
  if (bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return "image/jpeg";
  if (ascii(bytes, 0, 4) === "RIFF" && ascii(bytes, 8, 4) === "WEBP") return "image/webp";
  return null;
}

export class NotAnImage extends Error {
  constructor(url: string, contentType: string | null) {
    super(`Not an image: ${url} (${contentType ?? "no content type"})`);
    this.name = "NotAnImage";
  }
}

export async function fetchImageBitmap(url: string, signal?: AbortSignal): Promise<ImageBitmap> {
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`Image fetch failed: ${url} (HTTP ${res.status})`);
  const bytes = new Uint8Array(await res.arrayBuffer());
  const type = sniffImage(bytes);
  if (!type) throw new NotAnImage(url, res.headers.get("content-type"));
  signal?.throwIfAborted();
  return createImageBitmap(new Blob([bytes], { type }), {
    premultiplyAlpha: "none",
    colorSpaceConversion: "none",
  });
}
