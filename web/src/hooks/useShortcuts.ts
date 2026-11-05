import { useEffect } from "react";
import { controls } from "../lib/controls";
import { useStore } from "../store";

/** Space play/pause, Shift+→ skip, Shift+← previous, M mute, L loop. ("/" for search lives in SearchBox.) */
export function useShortcuts() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.closest("input, textarea, select, [contenteditable], [role=slider]")) return;
      if (e.ctrlKey || e.metaKey || e.altKey || !useStore.getState().guildId) return;

      if (e.code === "Space" && !target.closest("button, a")) {
        e.preventDefault();
        controls.togglePause();
      } else if (e.shiftKey && e.key === "ArrowRight") {
        e.preventDefault();
        controls.skip();
      } else if (e.shiftKey && e.key === "ArrowLeft") {
        e.preventDefault();
        controls.previous();
      } else if (e.key.toLowerCase() === "m" && !e.shiftKey) {
        controls.toggleMute();
      } else if (e.key.toLowerCase() === "l" && !e.shiftKey) {
        controls.cycleLoop();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
}
