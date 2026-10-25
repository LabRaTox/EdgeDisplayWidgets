import i18n from "../i18n";
import type { Localized } from "../types";

/** A manifest text in the window's language, or the first one there is. */
export function pick(value: Localized | null | undefined, fallback = ""): string {
  if (!value) return fallback;
  if (typeof value === "string") return value;
  return value[i18n.language] ?? value.en ?? Object.values(value)[0] ?? fallback;
}
