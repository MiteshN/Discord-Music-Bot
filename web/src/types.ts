export type LoopMode = "off" | "track" | "queue";
export type Source = "youtube" | "spotify" | "soundcloud" | "bandcamp" | "web";

export interface Song {
  id: number;
  title: string;
  url: string;
  duration: number;
  thumbnail: string;
  artist: string;
  requester: string;
  requester_id: string;
  requester_avatar: string;
  source: Source;
  live: boolean;
}

export interface Listener {
  id: string;
  name: string;
  avatar: string;
}

export interface PlayerState {
  current: Song | null;
  position: number;
  rate: number;
  paused: boolean;
  volume: number;
  loop: LoopMode;
  effect: { key: string; label: string } | null;
  queue: Song[];
  queue_length: number;
  queue_duration: number;
  history: Song[];
  twenty_four_seven: boolean;
  voice: { channel: string; listeners: Listener[] } | null;
  skip_votes: number;
  skip_needed: number;
  timestamp: number;
}

export type PositionUpdate = Pick<PlayerState, "position" | "rate" | "paused" | "timestamp">;

export interface Guild {
  id: string;
  name: string;
  icon: string | null;
  playing: boolean;
}

export interface User {
  id: string;
  username: string;
  avatar: string;
}

export interface Effect {
  key: string;
  label: string;
}

export interface BotInfo {
  name: string;
  avatar: string;
  effects: Effect[];
  spotify: boolean;
  dj_role: string;
}

export interface SpotifySong {
  title: string;
  artist: string;
  name: string;
  duration: number;
  thumbnail: string;
  url: string;
}

export interface SpotifyAlbum {
  title: string;
  artist: string;
  tracks: number;
  year: string;
  thumbnail: string;
  url: string;
}

export interface Video {
  title: string;
  url: string;
  duration: number;
  thumbnail: string;
}

export interface SearchResults {
  songs: SpotifySong[];
  albums: SpotifyAlbum[];
  videos: Video[];
}

export interface LyricLine {
  time: number;
  text: string;
}

export interface LyricsData {
  song_id: number;
  title: string;
  plain: string;
  synced: LyricLine[];
  source: string;
}

export interface Activity {
  text: string;
  actor: string;
  actor_id: string | null;
}

export type SocketMessage =
  | { type: "state"; data: PlayerState }
  | { type: "position"; data: PositionUpdate }
  | { type: "activity"; data: Activity };
