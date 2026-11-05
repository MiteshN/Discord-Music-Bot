import { isRunning, useStore } from "../store";
import type { LoopMode, PlayerState, Song } from "../types";

const get = () => useStore.getState();
let lastVolume = 100;

/** Where playback is right now, for freezing the bar at the right spot on pause. */
function livePosition(s: PlayerState): number {
  if (!isRunning(s)) return s.position;
  return s.position + ((performance.now() - get().syncedAt) / 1000) * s.rate;
}

function withoutSong(s: PlayerState, id: number): PlayerState {
  const song = s.queue.find((q) => q.id === id);
  if (!song) return s;
  return {
    ...s,
    queue: s.queue.filter((q) => q.id !== id),
    queue_length: s.queue_length - 1,
    queue_duration: s.queue_duration - song.duration,
  };
}

function moved(queue: Song[], id: number, to: number): Song[] {
  const from = queue.findIndex((q) => q.id === id);
  if (from < 0) return queue;
  const next = [...queue];
  const [song] = next.splice(from, 1);
  next.splice(to, 0, song);
  return next;
}

const LOOP_ORDER: LoopMode[] = ["off", "track", "queue"];

export const controls = {
  canControl(): boolean {
    const p = get().player;
    return !!p?.current && !!p.voice;
  },

  togglePause() {
    if (!controls.canControl()) return;
    get().act("pause", {}, { optimistic: (s) => ({ ...s, position: livePosition(s), paused: !s.paused }) });
  },

  skip() {
    if (controls.canControl()) get().act("skip");
  },

  previous() {
    const p = get().player;
    if (p?.voice && p.history.length) get().act("previous");
  },

  stop() {
    get().act("stop", {}, { announce: true });
  },

  seek(position: number) {
    get().act("seek", { position }, { optimistic: (s) => ({ ...s, position }) });
  },

  cycleLoop() {
    const p = get().player;
    if (!p) return;
    const mode = LOOP_ORDER[(LOOP_ORDER.indexOf(p.loop) + 1) % LOOP_ORDER.length];
    get().act("loop", { mode }, { optimistic: (s) => ({ ...s, loop: mode }) });
  },

  setVolume(volume: number) {
    if (volume > 0) lastVolume = volume;
    get().act("volume", { volume }, { optimistic: (s) => ({ ...s, volume }) });
  },

  toggleMute() {
    const p = get().player;
    if (!p) return;
    if (p.volume > 0) {
      lastVolume = p.volume; // even if it was set from Discord
      controls.setVolume(0);
    } else {
      controls.setVolume(lastVolume || 100);
    }
  },

  setEffect(key: string, label: string) {
    get().act(
      "effect",
      { key },
      {
        key: "effect",
        optimistic: (s) => ({ ...s, effect: key ? { key, label } : null, position: livePosition(s) }),
      },
    );
  },

  set247(enabled: boolean) {
    get().act("247", { enabled }, { announce: true, optimistic: (s) => ({ ...s, twenty_four_seven: enabled }) });
  },

  remove(id: number) {
    get().act("remove", { id }, { key: `remove:${id}`, optimistic: (s) => withoutSong(s, id) });
  },

  move(id: number, to: number) {
    get().act("move", { id, to }, { key: "move", optimistic: (s) => ({ ...s, queue: moved(s.queue, id, to) }) });
  },

  skipTo(id: number) {
    get().act("skipto", { id }, { key: `skipto:${id}` });
  },

  shuffle() {
    get().act("shuffle", {}, { announce: true });
  },

  clear() {
    get().act(
      "clear",
      {},
      { announce: true, optimistic: (s) => ({ ...s, queue: [], queue_length: 0, queue_duration: 0 }) },
    );
  },

  add(query: string, top = false) {
    return get().act("add", { query, top }, { announce: true, key: "add" });
  },

  setAutoplay(enabled: boolean) {
    get().act("autoplay", { enabled }, { announce: true, optimistic: (s) => ({ ...s, autoplay: enabled }) });
  },

  removeDuplicates() {
    get().act("removedupes", {}, { announce: true });
  },

  removeAbsent() {
    get().act("removeabsent", {}, { announce: true });
  },

  removeMine() {
    const me = get().user?.id;
    if (me) get().act("removeuser", { user_id: me }, { announce: true });
  },

  saveToDMs() {
    get().act("save", {}, { announce: true });
  },

  playRecent(count = 10) {
    get().act("playrecent", { count }, { announce: true, key: "playrecent" });
  },

  async saveQueue(name: string) {
    const message = await get().act("savequeue", { name }, { announce: true });
    if (message) get().loadPlaylists();
  },

  async addCurrentTo(name: string) {
    const message = await get().act("savecurrent", { name }, { announce: true, key: `savecurrent:${name}` });
    if (message) get().loadPlaylists();
  },

  loadPlaylist(name: string, shuffle = false) {
    get().act("loadplaylist", { name, shuffle }, { announce: true, key: `load:${name}` });
  },
};
