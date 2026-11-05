import { create } from "zustand";
import { ApiError, api } from "./lib/api";
import type { Activity, BotInfo, Guild, PlayerState, Playlist, PositionUpdate, User } from "./types";

export type AuthStatus = "loading" | "signed-out" | "signed-in" | "offline";
export type Connection = "idle" | "connecting" | "live" | "reconnecting";
export type Panel = "queue" | "lyrics" | "playlists" | "history";
export type MobileView = "player" | Panel;
export type ToastKind = "info" | "success" | "error" | "activity";

export interface Toast {
  id: number;
  text: string;
  kind: ToastKind;
  actor?: string;
}

interface ActOptions {
  /** Apply this to the local state straight away; the server's next push confirms or corrects it. */
  optimistic?: (state: PlayerState) => PlayerState;
  /** Show the server's reply as a toast. */
  announce?: boolean;
  /** Key for the busy indicator; defaults to the action name. */
  key?: string;
}

interface Store {
  auth: AuthStatus;
  user: User | null;
  bot: BotInfo | null;
  guilds: Guild[];
  guildId: string | null;
  player: PlayerState | null;
  /** performance.now() when `player.position` was last synced */
  syncedAt: number;
  connection: Connection;
  busy: Record<string, boolean>;
  toasts: Toast[];
  panel: Panel;
  mobileView: MobileView;
  searchOpen: boolean;
  statsOpen: boolean;
  playlists: Playlist[] | null;

  boot(): Promise<void>;
  refreshGuilds(): Promise<void>;
  selectGuild(id: string): void;
  setPlayer(state: PlayerState): void;
  syncPosition(update: PositionUpdate): void;
  setConnection(connection: Connection): void;
  act(action: string, args?: Record<string, unknown>, options?: ActOptions): Promise<string | null>;
  onActivity(activity: Activity): void;
  toast(text: string, kind?: ToastKind, actor?: string): void;
  dismiss(id: number): void;
  signedOut(): void;
  signOut(): Promise<void>;
  setPanel(panel: Panel): void;
  setMobileView(view: MobileView): void;
  setSearchOpen(open: boolean): void;
  setStatsOpen(open: boolean): void;
  loadPlaylists(): Promise<void>;
  playlistAction(action: string, args: Record<string, unknown>, success?: string): Promise<string | null>;
}

const GUILD_KEY = "mugetsu.guild";
let toastId = 0;

function storedGuild(): string | null {
  try {
    return localStorage.getItem(GUILD_KEY);
  } catch {
    return null;
  }
}

export const useStore = create<Store>((set, get) => ({
  auth: "loading",
  user: null,
  bot: null,
  guilds: [],
  guildId: null,
  player: null,
  syncedAt: 0,
  connection: "idle",
  busy: {},
  toasts: [],
  panel: "queue",
  mobileView: "player",
  searchOpen: false,
  statsOpen: false,
  playlists: null,

  async boot() {
    try {
      const { user, bot } = await api.me();
      const guilds = await api.guilds();
      set({ auth: "signed-in", user, bot, guilds });
      const saved = storedGuild();
      const initial =
        guilds.find((g) => g.id === saved) ?? guilds.find((g) => g.playing) ?? (guilds.length === 1 ? guilds[0] : null);
      if (initial) get().selectGuild(initial.id);
    } catch (err) {
      set({ auth: err instanceof ApiError && err.status === 401 ? "signed-out" : "offline" });
    }
  },

  async refreshGuilds() {
    try {
      const guilds = await api.guilds();
      const { guildId, player } = get();
      // Our own server's live state is fresher than the list
      set({
        guilds: guilds.map((g) => (g.id === guildId && player ? { ...g, playing: !!(player.current && player.voice) } : g)),
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) get().signedOut();
    }
  },

  selectGuild(id) {
    if (id === get().guildId) return;
    try {
      localStorage.setItem(GUILD_KEY, id);
    } catch {
      /* storage unavailable */
    }
    set({ guildId: id, player: null, connection: "connecting", busy: {} });
  },

  setPlayer(state) {
    const { guildId, guilds } = get();
    const playing = !!(state.current && state.voice);
    set({
      player: state,
      syncedAt: performance.now(),
      guilds: guilds.map((g) => (g.id === guildId && g.playing !== playing ? { ...g, playing } : g)),
    });
  },

  syncPosition(update) {
    const player = get().player;
    if (!player) return;
    set({ player: { ...player, ...update }, syncedAt: performance.now() });
  },

  setConnection(connection) {
    set({ connection });
  },

  async act(action, args = {}, options = {}) {
    const { guildId, player } = get();
    if (!guildId) return null;
    const key = options.key ?? action;
    if (options.optimistic && player) {
      set({ player: options.optimistic(player), syncedAt: performance.now() });
    }
    set((s) => ({ busy: { ...s.busy, [key]: true } }));
    try {
      const { message } = await api.act(guildId, action, args);
      if (options.announce) get().toast(message, "success");
      return message;
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        get().signedOut();
        return null;
      }
      get().toast((err as Error).message, "error");
      // Undo any optimistic change by fetching the real state
      if (options.optimistic && get().guildId === guildId) {
        api.state(guildId).then((s) => get().guildId === guildId && get().setPlayer(s)).catch(() => {});
      }
      return null;
    } finally {
      set((s) => {
        const busy = { ...s.busy };
        delete busy[key];
        return { busy };
      });
    }
  },

  onActivity(activity) {
    if (activity.actor_id && activity.actor_id === get().user?.id) return; // we already know what we did
    get().toast(activity.text, "activity", activity.actor);
  },

  toast(text, kind = "info", actor) {
    const id = ++toastId;
    set((s) => ({ toasts: [...s.toasts.slice(-3), { id, text, kind, actor }] }));
    setTimeout(() => get().dismiss(id), kind === "error" ? 6000 : 3500);
  },

  dismiss(id) {
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
  },

  signedOut() {
    set({ auth: "signed-out", user: null, guildId: null, player: null, connection: "idle" });
  },

  async signOut() {
    try {
      await api.logout();
    } finally {
      get().signedOut();
    }
  },

  setPanel(panel) {
    set({ panel });
  },

  setMobileView(mobileView) {
    set({ mobileView, ...(mobileView !== "player" ? { panel: mobileView } : {}) });
  },

  setSearchOpen(searchOpen) {
    set({ searchOpen });
  },

  setStatsOpen(statsOpen) {
    set({ statsOpen });
  },

  async loadPlaylists() {
    try {
      set({ playlists: await api.playlists() });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) get().signedOut();
      else get().toast((err as Error).message, "error");
    }
  },

  async playlistAction(action, args, success) {
    try {
      const { message } = await api.playlistAction(action, args);
      if (success !== undefined) get().toast(success || message, "success");
      get().loadPlaylists();
      return message;
    } catch (err) {
      get().toast((err as Error).message, "error");
      return null;
    }
  },
}));

/** Is something actually playing right now (not paused, bot in voice)? */
export function isRunning(player: PlayerState | null): boolean {
  return !!player?.current && !player.paused && !!player.voice;
}
