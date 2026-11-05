import { MicVocal } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { usePosition } from "../hooks/usePosition";
import { api } from "../lib/api";
import { controls } from "../lib/controls";
import { activeLine } from "../lib/format";
import { useStore } from "../store";
import type { LyricsData } from "../types";
import { Spinner } from "./ui/Buttons";

// Lyrics don't change: remember them for the session
const cache = new Map<string, LyricsData>();

function useLyrics(guildId: string | null, songId: number | undefined) {
  const key = guildId && songId ? `${guildId}:${songId}` : "";
  const [result, setResult] = useState<{ key: string; data: LyricsData | null; error: boolean }>({
    key: "",
    data: null,
    error: false,
  });

  useEffect(() => {
    if (!key || !guildId || cache.has(key)) return;
    const controller = new AbortController();
    api
      .lyrics(guildId, controller.signal)
      .then((data) => {
        // The song may have changed while we waited; only keep lyrics for the one we asked about
        const k = `${guildId}:${data.song_id}`;
        cache.set(k, data);
        setResult({ key: k, data, error: false });
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") setResult({ key, data: null, error: true });
      });
    return () => controller.abort();
  }, [key, guildId]);

  if (!key) return { status: "idle" as const, data: null };
  const data = cache.get(key) ?? (result.key === key ? result.data : null);
  if (data) return { status: "ready" as const, data };
  if (result.key === key && result.error) return { status: "error" as const, data: null };
  return { status: "loading" as const, data: null };
}

function Synced({ data }: { data: LyricsData }) {
  const position = usePosition();
  const box = useRef<HTMLDivElement>(null);
  const userScrolled = useRef(0);
  const current = activeLine(data.synced, position + 0.25);

  useEffect(() => {
    if (current < 0 || Date.now() - userScrolled.current < 4000) return;
    const el = box.current?.querySelector<HTMLElement>(`[data-line="${current}"]`);
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [current]);

  const markScrolled = () => {
    userScrolled.current = Date.now();
  };

  return (
    <div
      ref={box}
      onWheel={markScrolled}
      onTouchMove={markScrolled}
      className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-6 py-[18vh] [mask-image:linear-gradient(transparent,black_15%,black_85%,transparent)]"
    >
      {data.synced.map((line, i) => (
        <button
          key={i}
          type="button"
          data-line={i}
          onClick={() => controls.seek(Math.floor(line.time))}
          title="Jump here"
          className={`block w-full origin-left py-1.5 text-left text-[22px] font-bold leading-snug tracking-tight transition-all duration-300 ${
            i === current ? "scale-100 text-ink" : i < current ? "scale-[0.98] text-ink-3/70 hover:text-ink-2" : "scale-[0.98] text-ink-3 hover:text-ink-2"
          }`}
        >
          {line.text || "♪"}
        </button>
      ))}
    </div>
  );
}

export function Lyrics() {
  const guildId = useStore((s) => s.guildId);
  const song = useStore((s) => s.player?.current);
  const { status, data } = useLyrics(guildId, song?.id);
  const hasSynced = useMemo(() => !!data?.synced.length, [data]);

  if (!song) {
    return (
      <Empty title="Nothing playing" text="Lyrics show up here, in time with the music, when a song is playing." />
    );
  }
  if (status === "loading") {
    return (
      <div className="flex flex-1 items-center justify-center gap-3 text-sm text-ink-3">
        <Spinner /> Finding lyrics…
      </div>
    );
  }
  if (status === "error" || !data || !data.plain) {
    return <Empty title="No lyrics found" text={`We couldn't find lyrics for “${song.title}”.`} />;
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {hasSynced ? (
        <Synced data={data} />
      ) : (
        <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto whitespace-pre-line px-6 pb-6 text-[17px] font-medium leading-relaxed text-ink-2">
          {data.plain}
        </div>
      )}
      <p className="border-t border-line px-6 py-2.5 text-xs text-ink-3">
        {hasSynced ? "Synced lyrics" : "Lyrics"} from {data.source}
        {hasSynced && " · tap a line to jump there"}
      </p>
    </div>
  );
}

function Empty({ title, text }: { title: string; text: string }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 px-8 pb-12 text-center text-ink-3">
      <span className="grid size-14 place-items-center rounded-2xl bg-panel-2">
        <MicVocal size={24} />
      </span>
      <p className="text-[15px] font-medium text-ink-2">{title}</p>
      <p className="max-w-xs text-sm">{text}</p>
    </div>
  );
}
