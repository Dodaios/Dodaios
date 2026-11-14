/**
 * Pictures put into a document: embedded in its Markdown as a data URI.
 *
 * The page has no network, so a picture lives inside the document's text
 * (`shell.safe_image` keeps raster data URIs only), and the whole body is
 * capped at `MAX_BODY_CHARS`. A picture is therefore scaled down and
 * re-encoded until it fits in what is left of the document, and refused with
 * a clear sentence when it cannot be made small enough to stay readable.
 */

/** Mirrors `MAX_IMAGE_CHARS` in `dodaios/nodes/shell.py`. */
export const MAX_IMAGE_CHARS = 400_000;
/** The longest side a picture starts at: wider than the page's 720 px text column, sharp on a Retina screen. */
export const START_SIDE = 1440;
/** Below this longest side a picture is no longer worth showing. */
export const MIN_SIDE = 320;

export type PictureResult = { ok: true; src: string } | { ok: false; reason: "not_picture" | "too_large" | "unreadable" };

export interface PictureEncoder {
  /** The picture's size in pixels. */
  size: { width: number; height: number };
  /** The picture drawn at this size as a data URI. */
  encode: (width: number, height: number, quality: number) => string;
}

/**
 * Pick the largest size and quality that fits in `budget` characters. Pure,
 * so the stepping is testable without a canvas.
 */
export function fitPicture(encoder: PictureEncoder, budget: number): string | null {
  const limit = Math.min(budget, MAX_IMAGE_CHARS);
  const { width, height } = encoder.size;
  const longest = Math.max(width, height, 1);
  let side = Math.min(longest, START_SIDE);
  while (side >= MIN_SIDE || side === longest) {
    const scale = side / longest;
    const w = Math.max(1, Math.round(width * scale));
    const h = Math.max(1, Math.round(height * scale));
    for (const quality of [0.86, 0.72, 0.6]) {
      const src = encoder.encode(w, h, quality);
      if (src.length <= limit) return src;
    }
    if (side <= MIN_SIDE) break;
    side = Math.max(MIN_SIDE, Math.round(side * 0.75));
  }
  return null;
}

function loadImage(file: Blob): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("unreadable picture"));
    };
    image.src = url;
  });
}

/** A picture file as a data URI that fits in `budget` characters of the document. */
export async function pictureFromFile(file: Blob, budget: number): Promise<PictureResult> {
  if (!file.type.startsWith("image/") || file.type === "image/svg+xml") return { ok: false, reason: "not_picture" };
  let image: HTMLImageElement;
  try {
    image = await loadImage(file);
  } catch {
    return { ok: false, reason: "unreadable" };
  }
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  if (!context) return { ok: false, reason: "unreadable" };
  const src = fitPicture(
    {
      size: { width: image.naturalWidth, height: image.naturalHeight },
      encode: (width, height, quality) => {
        canvas.width = width;
        canvas.height = height;
        // JPEG has no transparency: a transparent area becomes white like the page.
        context.fillStyle = "#ffffff";
        context.fillRect(0, 0, width, height);
        context.drawImage(image, 0, 0, width, height);
        return canvas.toDataURL("image/jpeg", quality);
      },
    },
    budget,
  );
  return src ? { ok: true, src } : { ok: false, reason: "too_large" };
}

/** The picture files among dropped or pasted items. */
export function pictureFiles(list: FileList | null | undefined): File[] {
  return Array.from(list ?? []).filter((file) => file.type.startsWith("image/") && file.type !== "image/svg+xml");
}
