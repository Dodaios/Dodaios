/**
 * A picture the person picks, made fit for a slide.
 *
 * A node page runs without network, so an image slide holds its picture as
 * a `data:` URI of at most 400,000 characters (`shell.MAX_IMAGE_CHARS`).
 * Photos straight from a phone are many times that, so the picture is drawn
 * onto a canvas at most 1920 px wide (a slide is 1280 logical px, so that
 * stays sharp on a large screen) and encoded smaller until it fits: JPEG at
 * falling quality for photos, PNG kept for small pictures with transparency
 * (a logo), then smaller dimensions if it still does not fit.
 */
import { LIMITS } from "./deckModel";

const ACCEPTED = /^image\/(png|jpe?g|gif|webp|avif)$/;
const MAX_EDGE = 1920;

export class ImageTooLargeError extends Error {
  constructor() {
    super("The picture cannot be made small enough for a slide.");
    this.name = "ImageTooLargeError";
  }
}

export class ImageTypeError extends Error {
  constructor() {
    super("Only PNG, JPEG, GIF, WebP and AVIF pictures can go on a slide.");
    this.name = "ImageTypeError";
  }
}

export function isAcceptedImage(file: File): boolean {
  return ACCEPTED.test(file.type);
}

function readAsDataUrl(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error("The picture could not be read."));
    reader.readAsDataURL(file);
  });
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("The picture could not be opened."));
    image.src = url;
  });
}

/** The picture as a data URI a slide accepts. */
export async function imageForSlide(file: File): Promise<string> {
  if (!isAcceptedImage(file)) throw new ImageTypeError();
  const original = await readAsDataUrl(file);
  // Small enough already (and not an animation we would flatten for nothing): keep it as it is.
  if (original.length <= LIMITS.imageChars && !/^data:image\/avif/.test(original)) return original;
  const url = URL.createObjectURL(file);
  try {
    const image = await loadImage(url);
    const keepAlpha = file.type === "image/png" || file.type === "image/webp" || file.type === "image/gif";
    let scale = Math.min(1, MAX_EDGE / Math.max(image.naturalWidth, image.naturalHeight, 1));
    for (let round = 0; round < 8; round++) {
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
      canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
      const context = canvas.getContext("2d");
      if (!context) break;
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      if (keepAlpha) {
        const png = canvas.toDataURL("image/png");
        if (png.length <= LIMITS.imageChars) return png;
        // JPEG has no transparency: put white behind the picture, not black.
        context.globalCompositeOperation = "destination-over";
        context.fillStyle = "#ffffff";
        context.fillRect(0, 0, canvas.width, canvas.height);
      }
      for (const quality of [0.88, 0.8, 0.7, 0.6]) {
        const jpeg = canvas.toDataURL("image/jpeg", quality);
        if (jpeg.startsWith("data:image/jpeg") && jpeg.length <= LIMITS.imageChars) return jpeg;
      }
      scale *= 0.75;
    }
  } finally {
    URL.revokeObjectURL(url);
  }
  throw new ImageTooLargeError();
}

/** The first picture among dropped or pasted files, if any. */
export function firstImage(files: FileList | readonly File[] | null | undefined): File | null {
  if (!files) return null;
  for (const file of Array.from(files)) if (isAcceptedImage(file)) return file;
  return null;
}
