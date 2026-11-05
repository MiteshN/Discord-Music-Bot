import type { LyricLine } from "../types";

/** 0:05, 3:07, 1:02:09 */
export function formatTime(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor(total / 60) % 60;
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

/** "42 min", "2 hr 5 min" */
export function formatLong(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  if (h && m) return `${h} hr ${m} min`;
  if (h) return `${h} hr`;
  return `${Math.max(m, seconds > 0 ? 1 : 0)} min`;
}

export function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** Split "Artist - Title" so the title can be shown big and the artist small. */
export function splitTitle(title: string, artist = ""): { name: string; by: string } {
  if (artist && title.startsWith(`${artist} - `)) return { name: title.slice(artist.length + 3), by: artist };
  const i = title.indexOf(" - ");
  if (i > 0 && i < 60) return { name: title.slice(i + 3), by: title.slice(0, i) };
  return { name: title, by: artist };
}

/** Index of the lyric line being sung at `time`, or -1 before the first one. */
export function activeLine(lines: LyricLine[], time: number): number {
  let lo = 0;
  let hi = lines.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (lines[mid].time <= time) {
      found = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return found;
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => [...w][0])
    .join("")
    .slice(0, 3)
    .toUpperCase();
}

const YT_ID = /(?:v=|youtu\.be\/|\/shorts\/|\/embed\/)([A-Za-z0-9_-]{11})/;

export function youtubeThumb(url: string, size: "mqdefault" | "hqdefault" = "hqdefault"): string {
  const m = (url || "").match(YT_ID);
  return m ? `https://i.ytimg.com/vi/${m[1]}/${size}.jpg` : "";
}

export function isUrl(text: string): boolean {
  return /^https?:\/\//i.test(text.trim());
}
