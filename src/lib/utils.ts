import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function getFlagEmoji(countryCode: string | null | undefined): string {
  if (!countryCode) return "";
  const code = countryCode.split(',')[0].trim().toUpperCase(); // Handle comma-separated codes, take first
  if (code.length !== 2) return "";
  const codePoints = code
    .split("")
    .map((char) => 127397 + char.charCodeAt(0));
  return String.fromCodePoint(...codePoints);
}
