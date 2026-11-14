/**
 * A picture the person picks, made ready to live inside a design.
 *
 * A node page loads nothing from the network, so a picture is embedded as a
 * `data:` URI, and the server keeps one only when it is a raster picture of
 * at most `MAX_IMAGE_CHARS` characters (`shell.safe_image`). A photo from a
 * phone is far larger. Rather than refusing it, the picture is drawn again
 * smaller (JPEG for photos, PNG kept for pictures with transparency when it
 * fits) until it fits, which is what the person would have done by hand.
 */
import { MAX_IMAGE_CHARS } from "./designBlocks";

const ACCEPTED = /^image\/(png|jpeg|gif|webp|avif)$/;

export class ImageTooLargeError extends Error {
  constructor() {
    super("The picture cannot be made small enough to embed.");
    this.name = "ImageTooLargeError";
  }
}

export class ImageTypeError extends Error {
  constructor() {
    super("Only PNG, JPEG, GIF, WebP and AVIF pictures can be embedded.");
    this.name = "ImageTypeError";
  }
}

function readAsDataUrl(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("The picture could not be read."));
    reader.readAsDataURL(file);
  });
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("The picture could not be decoded."));
    image.src = src;
  });
}

/** Whether a data URI is one the server keeps as it is. */
export function fitsAsIs(dataUrl: string): boolean {
  return dataUrl.length <= MAX_IMAGE_CHARS && /^data:image\/(png|jpeg|jpg|gif|webp|avif);base64,/.test(dataUrl);
}

/**
 * The picture as an embeddable `data:` URI. Tries the file as it is, then
 * smaller versions: each step 80 % of the last side, JPEG at falling quality.
 */
export async function embedImage(file: File): Promise<string> {
  if (!ACCEPTED.test(file.type)) throw new ImageTypeError();
  const original = await readAsDataUrl(file);
  if (fitsAsIs(original)) return original;
  const image = await loadImage(original);
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  if (!context) throw new ImageTooLargeError();
  // Nothing on a design is wider than its largest artboard.
  let side = Math.min(2000, Math.max(image.naturalWidth, image.naturalHeight));
  for (let attempt = 0; attempt < 12 && side >= 64; attempt++) {
    const scale = side / Math.max(image.naturalWidth, image.naturalHeight);
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const quality = Math.max(0.5, 0.86 - attempt * 0.04);
    const asPng = file.type === "image/png" && attempt < 3 ? canvas.toDataURL("image/png") : "";
    if (asPng && fitsAsIs(asPng)) return asPng;
    // JPEG has no transparency: what was see-through turns white, not black.
    context.globalCompositeOperation = "destination-over";
    context.fillStyle = "#FFFFFF";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.globalCompositeOperation = "source-over";
    const asJpeg = canvas.toDataURL("image/jpeg", quality);
    if (fitsAsIs(asJpeg)) return asJpeg;
    side = Math.floor(side * 0.8);
  }
  throw new ImageTooLargeError();
}
