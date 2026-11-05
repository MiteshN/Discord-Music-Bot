import { useSyncExternalStore } from "react";
import { isRunning, useStore } from "../store";

// One shared 4 Hz clock for every progress bar and lyric highlight on the page
const listeners = new Set<() => void>();
let now = performance.now();
let timer: ReturnType<typeof setInterval> | undefined;

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (listeners.size === 1) {
    timer = setInterval(() => {
      now = performance.now();
      listeners.forEach((l) => l());
    }, 250);
  }
  return () => {
    listeners.delete(listener);
    if (!listeners.size) clearInterval(timer);
  };
}

const getNow = () => now;
const stillSubscribe = () => () => {};

/** The current track's position in seconds, interpolated between server updates. */
export function usePosition(): number {
  const player = useStore((s) => s.player);
  const syncedAt = useStore((s) => s.syncedAt);
  const running = isRunning(player);
  // Only tick while something is playing; a paused bar doesn't need re-rendering
  const clock = useSyncExternalStore(running ? subscribe : stillSubscribe, getNow);
  if (!player?.current) return 0;
  let t = player.position;
  if (running) t += (Math.max(0, clock - syncedAt) / 1000) * player.rate;
  return player.current.duration ? Math.min(t, player.current.duration) : t;
}
