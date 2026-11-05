import { ChartColumnBig, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "../lib/api";
import { splitTitle } from "../lib/format";
import { useStore } from "../store";
import type { Stats, StatsPeriod } from "../types";
import { Artwork } from "./ui/Artwork";
import { Avatar, Spinner } from "./ui/Buttons";

const PERIODS: { id: StatsPeriod; label: string }[] = [
  { id: "week", label: "This week" },
  { id: "month", label: "This month" },
  { id: "all", label: "All time" },
];

function hours(seconds: number): { value: string; unit: string } {
  if (seconds >= 3600) return { value: (seconds / 3600).toFixed(seconds >= 36000 ? 0 : 1), unit: "hours" };
  return { value: String(Math.round(seconds / 60)), unit: "minutes" };
}

function Tile({ value, unit, label }: { value: string | number; unit?: string; label: string }) {
  return (
    <div className="rounded-2xl border border-line bg-panel p-4">
      <div className="text-3xl font-bold tracking-tight tabular sm:text-4xl">
        {value}
        {unit && <span className="ml-1.5 text-base font-semibold text-ink-3">{unit}</span>}
      </div>
      <div className="mt-1 text-sm text-ink-2">{label}</div>
    </div>
  );
}

function Bar({ share }: { share: number }) {
  return (
    <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-white/8">
      <div className="h-full rounded-full bg-linear-to-r from-accent to-accent-3" style={{ width: `${Math.max(4, share * 100)}%` }} />
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-line bg-panel p-4">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-[0.14em] text-ink-3">{title}</h3>
      {children}
    </section>
  );
}

function Content({ stats }: { stats: Stats }) {
  if (!stats.plays) {
    return <p className="py-16 text-center text-ink-2">Nothing played yet in this period. Get the music going!</p>;
  }
  const listened = hours(stats.seconds);
  const topSong = stats.top_songs[0]?.plays || 1;
  const topPerson = stats.top_requesters[0]?.plays || 1;
  const topArtist = stats.top_artists[0]?.plays || 1;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <Tile value={stats.plays} label="songs played" />
        <Tile value={listened.value} unit={listened.unit} label="of music" />
        <Tile value={stats.requesters} label={stats.requesters === 1 ? "person queueing" : "people queueing"} />
      </div>
      <div className="grid gap-4 md:grid-cols-[1.4fr_1fr]">
        <Section title="Top songs">
          <ol className="space-y-2.5">
            {stats.top_songs.map((s, i) => {
              const { name, by } = splitTitle(s.title, s.artist);
              return (
                <li key={`${s.title}-${i}`} className="flex items-center gap-3">
                  <span className={`w-5 text-right text-sm font-bold tabular ${i < 3 ? "text-accent-3" : "text-ink-3"}`}>{i + 1}</span>
                  <Artwork src={s.thumbnail} url={s.url} className="size-10 shrink-0 rounded-lg" iconSize={14} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="truncate text-sm font-medium">{name}</span>
                      <span className="shrink-0 text-xs text-ink-3 tabular">{s.plays} plays</span>
                    </div>
                    {by && <div className="truncate text-xs text-ink-3">{by}</div>}
                    <Bar share={s.plays / topSong} />
                  </div>
                </li>
              );
            })}
          </ol>
        </Section>
        <div className="space-y-4">
          <Section title="Top requesters">
            <ol className="space-y-2.5">
              {stats.top_requesters.map((p, i) => (
                <li key={p.id} className="flex items-center gap-3">
                  <Avatar src={p.avatar} name={p.name} size={32} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="truncate text-sm font-medium">
                        {i === 0 && "👑 "}
                        {p.name}
                      </span>
                      <span className="shrink-0 text-xs text-ink-3 tabular">{p.plays}</span>
                    </div>
                    <Bar share={p.plays / topPerson} />
                  </div>
                </li>
              ))}
            </ol>
          </Section>
          {stats.top_artists.length > 0 && (
            <Section title="Top artists">
              <ol className="space-y-2">
                {stats.top_artists.map((a) => (
                  <li key={a.name}>
                    <div className="flex items-baseline justify-between gap-2 text-sm">
                      <span className="truncate font-medium">{a.name}</span>
                      <span className="shrink-0 text-xs text-ink-3 tabular">{a.plays}</span>
                    </div>
                    <Bar share={a.plays / topArtist} />
                  </li>
                ))}
              </ol>
            </Section>
          )}
        </div>
      </div>
    </div>
  );
}

export function StatsOverlay() {
  const open = useStore((s) => s.statsOpen);
  const setOpen = useStore((s) => s.setStatsOpen);
  const guildId = useStore((s) => s.guildId);
  const guildName = useStore((s) => s.guilds.find((g) => g.id === s.guildId)?.name ?? "This server");
  const [period, setPeriod] = useState<StatsPeriod>("week");
  const [result, setResult] = useState<{ key: string; stats: Stats | null; error: string }>({ key: "", stats: null, error: "" });
  const key = `${guildId}:${period}`;

  useEffect(() => {
    if (!open || !guildId) return;
    const controller = new AbortController();
    api
      .stats(guildId, period, controller.signal)
      .then((stats) => setResult({ key, stats, error: "" }))
      .catch((err: Error) => err.name !== "AbortError" && setResult({ key, stats: null, error: err.message }));
    return () => controller.abort();
  }, [open, guildId, period, key]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  if (!open) return null;
  const current = result.key === key ? result : null;

  return (
    <div className="fixed inset-0 z-50 flex animate-fade-in items-start justify-center overflow-y-auto bg-black/70 p-3 pt-[max(0.75rem,env(safe-area-inset-top))] backdrop-blur-md [animation-duration:0.2s] sm:p-8" onClick={() => setOpen(false)}>
      <div role="dialog" aria-label="Server stats" className="w-full max-w-4xl animate-rise rounded-[28px] border border-line-2 bg-[#100f17]/95 p-5 shadow-2xl sm:p-7" onClick={(e) => e.stopPropagation()}>
        <div className="mb-5 flex flex-wrap items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl bg-accent/20 text-accent-3">
            <ChartColumnBig size={20} />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-xl font-bold tracking-tight">{guildName}</h2>
            <p className="text-sm text-ink-3">Your server's listening, wrapped</p>
          </div>
          <div role="tablist" className="flex gap-1 rounded-xl bg-panel p-1">
            {PERIODS.map((p) => (
              <button
                key={p.id}
                type="button"
                role="tab"
                aria-selected={period === p.id}
                onClick={() => setPeriod(p.id)}
                className={`rounded-lg px-3 py-1.5 text-sm font-semibold transition-colors ${period === p.id ? "bg-panel-3 text-ink" : "text-ink-3 hover:text-ink-2"}`}
              >
                {p.label}
              </button>
            ))}
          </div>
          <button type="button" onClick={() => setOpen(false)} aria-label="Close" className="grid size-9 place-items-center rounded-xl text-ink-2 hover:bg-panel-3 hover:text-ink">
            <X size={18} />
          </button>
        </div>
        {current?.stats ? (
          <Content stats={current.stats} />
        ) : current?.error ? (
          <p className="py-16 text-center text-danger">{current.error}</p>
        ) : (
          <div className="flex justify-center py-20">
            <Spinner size={24} />
          </div>
        )}
      </div>
    </div>
  );
}
