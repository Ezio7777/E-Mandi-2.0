export const MAX_IMAGES = 5;
export const MAX_SIZE_MB = 8;
export const ACCEPTED = ["image/jpeg", "image/png", "image/webp"];

export function validateFile(file: File): string | null {
  if (!ACCEPTED.includes(file.type)) return `${file.name}: use a JPG, PNG or WebP photo.`;
  if (file.size > MAX_SIZE_MB * 1024 * 1024) return `${file.name}: photo is larger than ${MAX_SIZE_MB} MB.`;
  return null;
}
