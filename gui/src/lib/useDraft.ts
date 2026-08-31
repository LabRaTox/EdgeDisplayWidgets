/**
 * Draft editing with an explicit save.
 *
 * The old touch sheet saved on every keystroke, which is right for a finger on
 * a 2560×720 strip but wrong here: this window edits commands, URLs and grid
 * templates, where a half-typed value is a broken value. So a view edits a
 * draft, and only a deliberate Save reaches the backend.
 *
 * The upstream value can change underneath us — someone edits the YAML, or a
 * second window saves. When that happens and the draft is untouched, we adopt
 * the new value silently; when it is touched, we leave the edit alone rather
 * than throwing away typing nobody asked us to discard.
 */

import { useCallback, useEffect, useRef, useState } from "react";

export type SaveState =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved" }
  | { kind: "error"; message: string };

export function useDraft<T>(upstream: T | null) {
  const [draft, setDraft] = useState<T | null>(upstream);
  const [dirty, setDirty] = useState(false);
  const [state, setState] = useState<SaveState>({ kind: "idle" });
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  // `save` is called from an event handler and must see the value as it is
  // *now*. A state updater would not do: it runs during the next render, not
  // when we ask.
  const draftRef = useRef(draft);
  draftRef.current = draft;

  // What was last taken over from upstream, compared by value.
  //
  // Not by reference: a view that builds its upstream object inline hands us a
  // new one on every render, and this effect would then run constantly. Any
  // render that happened to catch `dirty` before it was committed would drop
  // the edit that had just been made, which looked like a click that did not
  // register while the unsaved-changes bar was already showing.
  const adopted = useRef<string | null>(null);

  useEffect(() => {
    if (upstream === null) return;
    if (dirtyRef.current) return;
    const value = JSON.stringify(upstream);
    if (value === adopted.current) return;
    adopted.current = value;
    setDraft(upstream);
  }, [upstream]);

  const edit = useCallback((update: (current: T) => T) => {
    setDraft((current) => (current === null ? current : update(current)));
    setDirty(true);
    setState({ kind: "idle" });
  }, []);

  const reset = useCallback(() => {
    adopted.current = upstream === null ? null : JSON.stringify(upstream);
    setDraft(upstream);
    setDirty(false);
    setState({ kind: "idle" });
  }, [upstream]);

  const save = useCallback(async (persist: (value: T) => Promise<void>) => {
    const current = draftRef.current;
    if (current === null) return;
    setState({ kind: "saving" });
    try {
      await persist(current);
      setDirty(false);
      setState({ kind: "saved" });
    } catch (err) {
      setState({
        kind: "error",
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }, []);

  return { draft, dirty, state, edit, reset, save };
}
