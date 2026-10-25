/**
 * Drop zones for files from the file manager, in a browser tab and in the
 * window.
 *
 * In a browser the file arrives in `dataTransfer.files`. In the Tauri window
 * it does not: when dragging from the file manager, WebKitGTK reports
 * `files` empty and only announces `text/uri-list` (measured with Dolphin
 * under Plasma 6, the same as in DECK//SWITCH). In the window, Tauri handles
 * the drop instead. It reports the paths and the pointer position; the
 * position says which zone was meant, and the window reads the file through
 * `read_dropped_file`.
 */

import { invoke, isTauri } from "@tauri-apps/api/core";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { useEffect, useRef, useState, type DragEvent } from "react";

import i18n from "../i18n";

type Zone = {
  element: HTMLElement;
  setOver: (over: boolean) => void;
  onFiles: (files: File[]) => void;
  onError: (text: string) => void;
};

const zones = new Set<Zone>();
let tauriListening = false;

/**
 * The zone under a position Tauri reports in physical pixels.
 *
 * With display scaling the conversion can be off. With only one zone on the
 * page, that one is meant, hit or not.
 */
function zoneAt(position: { x: number; y: number }): Zone | null {
  const scale = window.devicePixelRatio || 1;
  const element = document.elementFromPoint(position.x / scale, position.y / scale);
  if (element) {
    for (const zone of zones) {
      if (zone.element.contains(element)) return zone;
    }
  }
  return zones.size === 1 ? [...zones][0]! : null;
}

function listenToTauri(): void {
  if (tauriListening) return;
  tauriListening = true;
  void getCurrentWebview()
    .onDragDropEvent(({ payload }) => {
      if (payload.type === "leave") {
        for (const zone of zones) zone.setOver(false);
        return;
      }
      const target = zoneAt(payload.position);
      for (const zone of zones) zone.setOver(zone === target && payload.type !== "drop");
      if (payload.type !== "drop" || !target) return;
      readPaths(payload.paths)
        .then((files) => {
          if (files.length > 0) target.onFiles(files);
          else target.onError(i18n.t("drop.missing"));
        })
        .catch((error) => target.onError(errorText(error)));
    })
    .catch((error) => {
      tauriListening = false;
      console.error("dropping into the window is not available:", error);
    });
}

async function readPaths(paths: string[]): Promise<File[]> {
  const files: File[] = [];
  for (const path of paths) {
    const content = await invoke<ArrayBuffer>("read_dropped_file", { path });
    const name = path.split("/").pop() || "file";
    files.push(new File([content], name, { type: typeOf(name) }));
  }
  return files;
}

/** The window reports codes only; the page knows the language. */
function errorText(error: unknown): string {
  const code = error instanceof Error ? error.message : String(error);
  if (code === "not-dropped") return i18n.t("drop.not_allowed");
  if (code === "not-a-file") return i18n.t("drop.not_a_file");
  if (code === "too-large") return i18n.t("drop.too_large", { mb: 64 });
  if (code.startsWith("io:")) return i18n.t("drop.read_failed", { detail: code.slice(3) });
  return code;
}

/** Media type by extension, as a browser would give a file. */
function typeOf(name: string): string {
  const extension = name.toLowerCase().split(".").pop() ?? "";
  const types: Record<string, string> = {
    zip: "application/zip",
    tar: "application/x-tar",
    gz: "application/gzip",
    tgz: "application/gzip",
  };
  return types[extension] ?? "application/octet-stream";
}

/**
 * Makes an element a drop zone.
 *
 * `ref` and the handlers in `props` go on the element, `over` says whether
 * something is being dragged over it. `onFiles` gets the dropped files,
 * `onError` a message when reading them fails.
 */
export function useDropZone<T extends HTMLElement = HTMLDivElement>(opts: {
  onFiles: (files: File[]) => void;
  onError: (text: string) => void;
}) {
  const ref = useRef<T>(null);
  const [over, setOver] = useState(false);
  // The callbacks change with every render; the zone is registered once.
  // Calls therefore go through this reference.
  const current = useRef(opts);
  current.current = opts;

  useEffect(() => {
    const element = ref.current;
    if (!element || !isTauri()) return;
    const zone: Zone = {
      element,
      setOver,
      onFiles: (files) => current.current.onFiles(files),
      onError: (text) => current.current.onError(text),
    };
    zones.add(zone);
    listenToTauri();
    return () => {
      zones.delete(zone);
    };
  }, []);

  // In a browser the file comes through the ordinary events.
  const props = {
    onDragOver: (event: DragEvent<T>) => {
      event.preventDefault();
      setOver(true);
    },
    onDragLeave: () => setOver(false),
    onDrop: (event: DragEvent<T>) => {
      event.preventDefault();
      setOver(false);
      const files = Array.from(event.dataTransfer.files);
      if (files.length > 0) current.current.onFiles(files);
    },
  };

  return { ref, over, props };
}
