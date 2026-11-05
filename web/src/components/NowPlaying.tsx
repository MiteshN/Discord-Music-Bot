import {
  Clock,
  ExternalLink,
  Pause,
  Play,
  Radio,
  Repeat,
  Repeat1,
  SkipBack,
  SkipForward,
  Sparkles,
  Square,
  Volume1,
  Volume2,
  VolumeX,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { usePosition } from "../hooks/usePosition";
import { controls } from "../lib/controls";
import { formatTime, splitTitle } from "../lib/format";
import { useStore } from "../store";
import type { PlayerState } from "../types";
import { Artwork } from "./ui/Artwork";
import { Avatar, Eq, IconButton, SourceBadge, Spinner } from "./ui/Buttons";
import { Slider } from "./ui/Slider";

function Badge({ icon: Icon, children, accent = false }: { icon: typeof Clock; children: string; accent?: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
        accent ? "bg-accent/18 text-accent-3" : "bg-panel-2 text-ink-2"
      }`}
    >
      <Icon size={13} /> {children}
    </span>
  );
}

function TrackInfo({ player }: { player: PlayerState }) {
  const cur = player.current;
  if (!cur) {
    return (
      <div className="mt-8 text-center">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-ink-3">
          {player.voice ? "Ready" : "Not connected"}
        </p>
        <h2 className="mt-2 text-2xl font-bold tracking-tight sm:text-3xl">
          {player.voice ? "Queue something up" : "Nothing playing"}
        </h2>
        <p className="mx-auto mt-2 max-w-sm text-[15px] leading-relaxed text-ink-2">
          {player.voice ? (
            <>
              Search above, or use <code className="rounded bg-panel-3 px-1.5 py-0.5 text-[13px]">/play</code> in Discord.
            </>
          ) : (
            <>
              Join a voice channel in this server, then search above or use{" "}
              <code className="rounded bg-panel-3 px-1.5 py-0.5 text-[13px]">/play</code>.
            </>
          )}
        </p>
      </div>
    );
  }

  const { name, by } = splitTitle(cur.title, cur.artist);
  const link = /^https?:\/\//.test(cur.url) ? cur.url : "";
  return (
    <div className="mt-6 w-full text-center">
      <p className="flex items-center justify-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-accent-3">
        <Eq paused={player.paused} />
        {player.paused ? "Paused" : "Now playing"}
      </p>
      <h2 className="mt-2.5 text-balance text-[26px] font-bold leading-tight tracking-tight sm:text-[32px]">
        {link ? (
          <a href={link} target="_blank" rel="noreferrer" className="group/link hover:underline decoration-ink-3 underline-offset-4">
            {name}
            <ExternalLink size={16} className="ml-1.5 inline align-baseline text-ink-3 opacity-0 transition-opacity group-hover/link:opacity-100" />
          </a>
        ) : (
          name
        )}
      </h2>
      {by && <p className="mt-1.5 truncate text-[17px] text-ink-2">{by}</p>}
      <div className="mt-3.5 flex flex-wrap items-center justify-center gap-2">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-panel-2 py-1 pl-1 pr-2.5 text-xs text-ink-2">
          <Avatar src={cur.requester_avatar} name={cur.requester} size={18} />
          {cur.requester}
        </span>
        <SourceBadge source={cur.source} />
        {player.effect && <Badge icon={Sparkles} accent>{player.effect.label}</Badge>}
        {player.loop !== "off" && <Badge icon={player.loop === "track" ? Repeat1 : Repeat}>{`Looping ${player.loop}`}</Badge>}
        {player.twenty_four_seven && <Badge icon={Clock}>24/7</Badge>}
        {cur.live && <Badge icon={Radio}>Live</Badge>}
      </div>
    </div>
  );
}

function Progress({ player }: { player: PlayerState }) {
  const position = usePosition();
  const [preview, setPreview] = useState<number | null>(null);
  const cur = player.current;
  const duration = cur?.duration ?? 0;
  const seekable = !!cur && !!player.voice && duration > 0 && !cur.live;
  const shown = preview ?? position;

  return (
    <div className="mt-5 w-full">
      <Slider
        label="Seek"
        value={Math.floor(position)}
        max={duration || 100}
        disabled={!seekable}
        onPreview={setPreview}
        onCommit={(v) => controls.seek(v)}
        format={formatTime}
        hoverTip
      />
      <div className="mt-1 flex justify-between text-xs text-ink-3 tabular">
        <span>{cur ? formatTime(shown) : "0:00"}</span>
        <span>{cur ? (cur.live ? "LIVE" : duration ? formatTime(duration) : "–:––") : "0:00"}</span>
      </div>
    </div>
  );
}

function Transport({ player }: { player: PlayerState }) {
  const busy = useStore((s) => s.busy);
  const [confirmStop, setConfirmStop] = useState(false);
  const active = !!player.current && !!player.voice;
  const LoopIcon = player.loop === "track" ? Repeat1 : Repeat;

  return (
    <div className="mt-3 flex items-center justify-center gap-2 sm:gap-4">
      <IconButton label={`Loop: ${player.loop} (L)`} active={player.loop !== "off"} onClick={controls.cycleLoop}>
        <LoopIcon size={20} />
      </IconButton>
      <IconButton
        label="Previous (Shift+←)"
        size="lg"
        disabled={!player.voice || !player.history.length}
        busy={busy.previous}
        onClick={controls.previous}
      >
        <SkipBack size={24} fill="currentColor" />
      </IconButton>
      <button
        type="button"
        onClick={controls.togglePause}
        disabled={!active}
        aria-label={player.paused ? "Play (Space)" : "Pause (Space)"}
        title={player.paused ? "Play (Space)" : "Pause (Space)"}
        className="grid size-[68px] place-items-center rounded-full bg-ink text-bg shadow-[0_14px_40px_-12px_rgb(167_139_250/0.8)] transition hover:scale-[1.04] active:scale-95 disabled:opacity-35 disabled:hover:scale-100"
      >
        {busy.pause ? (
          <Spinner size={24} className="!text-bg" />
        ) : active && !player.paused ? (
          <Pause size={28} fill="currentColor" strokeWidth={0} />
        ) : (
          <Play size={28} fill="currentColor" strokeWidth={0} className="translate-x-0.5" />
        )}
      </button>
      <div className="relative">
        <IconButton label="Skip (Shift+→)" size="lg" disabled={!active} busy={busy.skip} onClick={controls.skip}>
          <SkipForward size={24} fill="currentColor" />
        </IconButton>
        {player.skip_votes > 0 && player.skip_needed > 0 && (
          <span className="absolute -right-1 -top-1 rounded-full bg-accent px-1.5 text-[10px] font-bold leading-4 text-white tabular">
            {player.skip_votes}/{player.skip_needed}
          </span>
        )}
      </div>
      <IconButton
        label={confirmStop ? "Click again to stop and disconnect" : "Stop and disconnect"}
        tone="danger"
        disabled={!player.voice}
        busy={busy.stop}
        active={confirmStop}
        className={confirmStop ? "!bg-danger/20 !text-danger" : ""}
        onClick={() => {
          if (confirmStop) {
            setConfirmStop(false);
            controls.stop();
          } else {
            setConfirmStop(true);
            setTimeout(() => setConfirmStop(false), 3000);
          }
        }}
      >
        <Square size={18} fill="currentColor" />
      </IconButton>
    </div>
  );
}

function VolumeRow({ player }: { player: PlayerState }) {
  const [preview, setPreview] = useState<number | null>(null);
  const volume = preview ?? player.volume;
  const Icon = volume === 0 ? VolumeX : volume < 50 ? Volume1 : Volume2;

  return (
    <div className="mt-5 flex w-full items-center gap-3 rounded-2xl border border-line bg-panel px-3 py-2.5 sm:gap-4 sm:px-4">
      <IconButton label="Mute (M)" size="sm" onClick={controls.toggleMute}>
        <Icon size={18} />
      </IconButton>
      <Slider
        label="Volume"
        value={player.volume}
        max={100}
        onPreview={setPreview}
        onCommit={controls.setVolume}
        format={(v) => `${Math.round(v)}%`}
        className="flex-1"
      />
      <span
        className="w-10 text-right text-sm tabular text-ink-2"
        title="100% sends the original audio untouched, for the best quality"
      >
        {Math.round(volume)}%
      </span>
      <EffectsMenu player={player} />
      <div className="h-6 w-px bg-line-2" />
      <label className="flex cursor-pointer items-center gap-2.5 text-sm text-ink-2" title="Stay in the voice channel even when idle">
        <span>24/7</span>
        <input
          type="checkbox"
          className="peer sr-only"
          checked={player.twenty_four_seven}
          onChange={(e) => controls.set247(e.target.checked)}
        />
        <span className="relative h-6 w-10 rounded-full bg-panel-3 transition-colors after:absolute after:left-0.5 after:top-0.5 after:size-5 after:rounded-full after:bg-ink-2 after:shadow after:transition-transform peer-checked:bg-accent peer-checked:after:translate-x-4 peer-checked:after:bg-white peer-focus-visible:outline-2 peer-focus-visible:outline-accent-2" />
      </label>
    </div>
  );
}

function EffectsMenu({ player }: { player: PlayerState }) {
  const effects = useStore((s) => s.bot?.effects ?? []);
  const busy = useStore((s) => s.busy.effect);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const active = !!player.current && !!player.voice;
  const currentKey = player.effect?.key ?? "";

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const choose = (key: string, label: string) => {
    setOpen(false);
    if (key !== currentKey) controls.setEffect(key, label);
  };

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="true"
        title="Audio effects"
        className={`flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-sm font-medium transition-colors ${
          player.effect ? "bg-accent/20 text-accent-3 hover:bg-accent/28" : "text-ink-2 hover:bg-panel-3 hover:text-ink"
        }`}
      >
        {busy ? <Spinner size={15} /> : <Sparkles size={15} />}
        <span className="hidden max-w-24 truncate sm:block">{player.effect?.label ?? "Effects"}</span>
      </button>
      {open && (
        <div className="absolute bottom-full right-0 z-30 mb-2 w-[min(19rem,calc(100vw-2.5rem))] animate-pop rounded-2xl border border-line-2 bg-[#15141d]/95 p-3 shadow-[0_24px_60px_-15px_rgb(0_0_0/0.9)] backdrop-blur-2xl">
          <div className="mb-2.5 px-1 text-xs font-semibold uppercase tracking-[0.14em] text-ink-3">Effects</div>
          <div className="flex flex-wrap gap-1.5">
            {[{ key: "", label: "None" }, ...effects].map((e) => {
              const on = currentKey === e.key;
              return (
                <button
                  key={e.key || "none"}
                  type="button"
                  disabled={!active || busy}
                  aria-pressed={on}
                  onClick={() => choose(e.key, e.label)}
                  className={`rounded-full border px-3 py-1.5 text-[13px] font-medium transition-colors disabled:opacity-40 ${
                    on
                      ? "border-accent/60 bg-accent/20 text-accent-3"
                      : "border-line bg-panel text-ink-2 hover:border-line-2 hover:bg-panel-2 hover:text-ink"
                  }`}
                >
                  {e.label}
                </button>
              );
            })}
          </div>
          <p className="mt-3 px-1 text-xs leading-relaxed text-ink-3">
            {active
              ? "At 100% volume with no effect, Discord gets the original audio untouched."
              : "Effects can be changed while something is playing."}
          </p>
        </div>
      )}
    </div>
  );
}

export function NowPlaying() {
  const player = useStore((s) => s.player);

  if (!player) {
    return (
      <div className="mx-auto flex w-full max-w-[560px] flex-col items-center pt-4">
        <div className="aspect-square w-full max-w-[min(360px,38vh)] animate-pulse rounded-[28px] bg-panel-2" />
        <div className="mt-8 h-4 w-28 animate-pulse rounded bg-panel-2" />
        <div className="mt-4 h-8 w-64 animate-pulse rounded bg-panel-2" />
      </div>
    );
  }

  const cur = player.current;
  return (
    <section aria-label="Now playing" className="mx-auto flex w-full max-w-[560px] flex-col items-center">
      <div className="relative w-full max-w-[min(360px,38vh)]">
        {cur && (
          <Artwork
            src={cur.thumbnail}
            url={cur.url}
            className="absolute inset-4 -z-10 rounded-[28px] opacity-70 blur-3xl"
            loading="eager"
          />
        )}
        <Artwork
          src={cur?.thumbnail ?? ""}
          url={cur?.url}
          alt=""
          loading="eager"
          iconSize={56}
          className={`aspect-square w-full rounded-[28px] shadow-[0_30px_80px_-30px_rgb(0_0_0/0.9)] ring-1 ring-white/10 transition-transform duration-700 ${
            cur && !player.paused ? "scale-100" : "scale-[0.96]"
          }`}
        />
      </div>
      <TrackInfo player={player} />
      <Progress player={player} />
      <Transport player={player} />
      <VolumeRow player={player} />
    </section>
  );
}
