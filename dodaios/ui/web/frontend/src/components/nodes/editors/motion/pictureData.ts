/**
 * A picture the person picks, made small enough to live inside the clip.
 *
 * An image scene keeps its picture embedded in the spec (a `data:` URI): the
 * page runs in a sandbox with the network shut, so nothing can be fetched.
 * The spec keeps at most `MAX_IMAGE_CHARS` characters per picture, which a
 * phone photo exceeds many times over. So the picture is drawn onto a canvas
 * no larger than a film frame needs and encoded at falling quality (WebP
 * where the engine writes it, JPEG otherwise) until it fits.
 */
import { MAX_IMAGE_CHARS } from "./motionModel";

/** The longest edge a film needs: the wide stage is 1280 px across. */
const LONGEST_EDGE = 1600;
const QUALITIES = [0.86, 0.76, 0.66, 0.56, 0.46];

export class PictureError extends Error {
  constructor(readonly reason: "type" | "read" | "size") {
    super(reason);
    this.name = "PictureError";
  }
}

function load(file: Blob): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new PictureError("read"));
    };
    image.src = url;
  });
}

/** The encodings to try, best first: WebP keeps transparency and is small. */
function encoders(canvas: HTMLCanvasElement): string[] {
  const webp = canvas.toDataURL("image/webp", 0.8).startsWith("data:image/webp");
  return webp ? ["image/webp", "image/jpeg"] : ["image/jpeg"];
}

/**
 * `file` as a `data:` URI of at most `maxChars` characters.
 *
 * Throws `PictureError("type")` for something that is not a picture,
 * `"read"` when it cannot be decoded, `"size"` when even the smallest
 * encoding does not fit.
 */
export async function pictureToDataUri(file: Blob, maxChars: number = MAX_IMAGE_CHARS): Promise<string> {
  if (!file.type.startsWith("image/")) throw new PictureError("type");
  const image = await load(file);
  let scale = Math.min(1, LONGEST_EDGE / Math.max(image.naturalWidth, image.naturalHeight, 1));
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  if (!context) throw new PictureError("read");
  // Shrinking the frame is the second lever after quality: three rounds.
  for (let round = 0; round < 3; round += 1) {
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    for (const type of encoders(canvas)) {
      for (const quality of QUALITIES) {
        const uri = canvas.toDataURL(type, quality);
        if (uri.length <= maxChars) return uri;
      }
    }
    scale *= 0.7;
  }
  throw new PictureError("size");
}
