import { CircleCheck, CircleExclamationPoint, Disc3, Info, ListMusic, MicVocal, Pause, Play, RotateCcwClock, SkipForward, X } from "lucide-react";
import type { ReactNode } from "react";
import { controls } from "../lib/controls";
import { splitTitle } from "../lib/format";
import { useStore, type MobileView, type Panel } from "../store";
import { Artwork } from "./ui/Artwork";
import { IconButton } from "./ui/Buttons";

/** The current cover, hugely blurred, behind everything. */
export function Ambient() {
  const art = useStore((s) => s.player?.current?.thumbnail ?? "");
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden bg-bg">
      <div className="absolute -left-48 -top-48 size-[40rem] rounded-full bg-accent/20 blur-[140px]" />
      <div className="absolute -bottom-56 right-0 size-[34rem] rounded-full bg-sky-500/8 blur-[140px]" />
      {art && (
        <img
          key={art}
          src={art}
          alt=""
          referrerPolicy="no-referrer"
          className="absolute inset-[-15%] size-[130%] animate-fade-in object-cover opacity-30 blur-[100px] saturate-[1.6] [animation-duration:1.2s]"
        />
      )}
      <div className="absolute inset-0 bg-linear-to-b from-bg/45 via-bg/65 to-bg/90" />
    </div>
  );
}

const TOAST_ICONS = { info: Info, success: CircleCheck, error: CircleExclamationPoint, activity: Disc3 };

export function Toasts() {
  const toasts = useStore((s) => s.toasts);
  const dismiss = useStore((s) => s.dismiss);
  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 bottom-[calc(5.5rem+env(safe-area-inset-bottom))] z-50 flex flex-col items-center gap-2 px-4 lg:bottom-6 lg:items-end lg:px-8"
    >
      {toasts.map((t) => {
        const Icon = TOAST_ICONS[t.kind];
        return (
          <div
            key={t.id}
            role={t.kind === "error" ? "alert" : "status"}
            className={`pointer-events-auto flex w-full max-w-sm animate-rise items-start gap-3 rounded-2xl border px-4 py-3 text-sm shadow-[0_20px_50px_-15px_rgb(0_0_0/0.8)] backdrop-blur-2xl ${
              t.kind === "error" ? "border-danger/30 bg-[#2a1219]/90" : "border-line-2 bg-[#15141d]/90"
            }`}
          >
            <Icon
              size={18}
              className={`mt-px shrink-0 ${
                t.kind === "error" ? "text-danger" : t.kind === "success" ? "text-success" : "text-accent-3"
              }`}
            />
            <p className="min-w-0 flex-1 leading-snug">
              {t.actor && <span className="font-semibold text-ink">{t.actor} · </span>}
              <span className="text-ink-2">{t.text}</span>
            </p>
            <button type="button" onClick={() => dismiss(t.id)} aria-label="Dismiss" className="text-ink-3 hover:text-ink">
              <X size={15} />
            </button>
          </div>
        );
      })}
    </div>
  );
}

const PANELS: { id: Panel; label: string; icon: typeof ListMusic }[] = [
  { id: "queue", label: "Up next", icon: ListMusic },
  { id: "lyrics", label: "Lyrics", icon: MicVocal },
  { id: "history", label: "History", icon: RotateCcwClock },
];

export function PanelTabs() {
  const panel = useStore((s) => s.panel);
  const setPanel = useStore((s) => s.setPanel);
  const count = useStore((s) => s.player?.queue_length ?? 0);
  return (
    <div role="tablist" className="flex gap-1 p-3">
      {PANELS.map(({ id, label }) => (
        <button
          key={id}
          type="button"
          role="tab"
          aria-selected={panel === id}
          onClick={() => setPanel(id)}
          className={`flex items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-semibold transition-colors ${
            panel === id ? "bg-panel-3 text-ink" : "text-ink-3 hover:bg-panel-2 hover:text-ink-2"
          }`}
        >
          {label}
          {id === "queue" && count > 0 && (
            <span className="rounded-full bg-accent/25 px-1.5 text-[11px] leading-[18px] text-accent-3 tabular">{count}</span>
          )}
        </button>
      ))}
    </div>
  );
}

/** Bottom tab bar for phones and small tablets. */
export function MobileNav() {
  const view = useStore((s) => s.mobileView);
  const setView = useStore((s) => s.setMobileView);
  const count = useStore((s) => s.player?.queue_length ?? 0);
  const items: { id: MobileView; label: string; icon: typeof ListMusic }[] = [
    { id: "player", label: "Playing", icon: Disc3 },
    ...PANELS,
  ];
  return (
    <nav className="flex shrink-0 border-t border-line bg-black/50 pb-[env(safe-area-inset-bottom)] backdrop-blur-2xl lg:hidden">
      {items.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          type="button"
          onClick={() => setView(id)}
          aria-current={view === id || undefined}
          className={`relative flex flex-1 flex-col items-center gap-1 pb-2 pt-2.5 text-[11px] font-medium ${
            view === id ? "text-ink" : "text-ink-3"
          }`}
        >
          <Icon size={21} className={view === id ? "text-accent-3" : ""} />
          {label}
          {id === "queue" && count > 0 && (
            <span className="absolute left-1/2 top-1.5 ml-2 rounded-full bg-accent px-1.5 text-[10px] font-bold leading-4 text-white tabular">
              {count}
            </span>
          )}
        </button>
      ))}
    </nav>
  );
}

/** A slim now-playing bar above the tabs when the full player isn't on screen. */
export function MiniPlayer() {
  const player = useStore((s) => s.player);
  const setView = useStore((s) => s.setMobileView);
  const cur = player?.current;
  if (!player || !cur) return null;
  const { name, by } = splitTitle(cur.title, cur.artist);
  return (
    <div className="mx-3 mb-2 flex items-center gap-3 rounded-2xl border border-line-2 bg-[#17161f]/90 p-2 pr-1 shadow-xl backdrop-blur-2xl lg:hidden">
      <button type="button" onClick={() => setView("player")} className="flex min-w-0 flex-1 items-center gap-3 text-left">
        <Artwork src={cur.thumbnail} url={cur.url} className="size-11 shrink-0 rounded-xl" iconSize={16} />
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold">{name}</span>
          <span className="block truncate text-xs text-ink-3">{by || cur.requester}</span>
        </span>
      </button>
      <IconButton label={player.paused ? "Play" : "Pause"} onClick={controls.togglePause} disabled={!player.voice}>
        {player.paused ? <Play size={20} fill="currentColor" /> : <Pause size={20} fill="currentColor" />}
      </IconButton>
      <IconButton label="Skip" onClick={controls.skip} disabled={!player.voice}>
        <SkipForward size={20} fill="currentColor" />
      </IconButton>
    </div>
  );
}

export function Centered({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 px-8 pb-16 text-center">
      <span className="grid size-20 place-items-center rounded-[26px] border border-line bg-panel-2 text-accent-3 shadow-[0_20px_60px_-20px_rgb(139_92_246/0.6)]">
        {icon}
      </span>
      <h2 className="text-2xl font-bold tracking-tight">{title}</h2>
      <div className="max-w-sm text-[15px] leading-relaxed text-ink-2">{children}</div>
    </div>
  );
}
