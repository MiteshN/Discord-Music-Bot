import { Check, ChevronDown, LogOut, Search as SearchIcon, Volume2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import type { Listener } from "../types";
import { SearchBox } from "./Search";
import { GuildIcon } from "./ServerRail";
import { Avatar } from "./ui/Buttons";

function ConnectionDot() {
  const connection = useStore((s) => s.connection);
  const label = { idle: "Offline", connecting: "Connecting…", live: "Live", reconnecting: "Reconnecting…" }[connection];
  return (
    <span className="relative flex size-2.5 shrink-0" title={label}>
      {connection === "live" && <span className="absolute inset-0 animate-ping rounded-full bg-success/60 [animation-duration:2.5s]" />}
      <span
        className={`relative size-2.5 rounded-full ${
          connection === "live" ? "bg-success" : connection === "idle" ? "bg-ink-3" : "animate-pulse bg-amber-400"
        }`}
      />
      <span className="sr-only">{label}</span>
    </span>
  );
}

function Listeners({ listeners }: { listeners: Listener[] }) {
  if (!listeners.length) return null;
  const shown = listeners.slice(0, 5);
  const names = listeners.map((l) => l.name).join(", ");
  return (
    <span className="flex items-center gap-2" title={`Listening: ${names}`}>
      <span className="flex -space-x-1.5">
        {shown.map((l) => (
          <Avatar key={l.id} src={l.avatar} name={l.name} size={20} className="ring-2 ring-bg" />
        ))}
      </span>
      {listeners.length > shown.length && <span className="text-ink-3">+{listeners.length - shown.length}</span>}
    </span>
  );
}

function ServerPicker() {
  const guilds = useStore((s) => s.guilds);
  const guildId = useStore((s) => s.guildId);
  const selectGuild = useStore((s) => s.selectGuild);
  const user = useStore((s) => s.user);
  const signOut = useStore((s) => s.signOut);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const guild = guilds.find((g) => g.id === guildId);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  return (
    <div ref={ref} className="relative min-w-0 lg:hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex min-w-0 items-center gap-2.5 rounded-xl py-1 pr-2 text-left"
      >
        {guild ? <GuildIcon guild={guild} className="size-9 rounded-xl" /> : <span className="size-9 rounded-xl bg-panel-3" />}
        <span className="truncate text-[17px] font-semibold">{guild?.name ?? "Pick a server"}</span>
        <ChevronDown size={18} className={`shrink-0 text-ink-3 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="absolute left-0 top-full z-50 mt-2 w-72 animate-pop rounded-2xl border border-line-2 bg-[#121119]/95 p-1.5 shadow-2xl backdrop-blur-2xl">
          <div className="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-ink-3">Servers</div>
          <div className="scrollbar-thin max-h-[50vh] overflow-y-auto">
            {guilds.map((g) => (
              <button
                key={g.id}
                type="button"
                onClick={() => {
                  selectGuild(g.id);
                  setOpen(false);
                }}
                className="flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left hover:bg-panel-2"
              >
                <GuildIcon guild={g} className="size-8 rounded-lg" />
                <span className="min-w-0 flex-1 truncate text-sm font-medium">{g.name}</span>
                {g.playing && <Volume2 size={15} className="text-success" />}
                {g.id === guildId && <Check size={16} className="text-accent-3" />}
              </button>
            ))}
          </div>
          {user && (
            <button
              type="button"
              onClick={signOut}
              className="mt-1 flex w-full items-center gap-3 rounded-xl border-t border-line px-2.5 py-2.5 text-left text-sm text-ink-2 hover:bg-panel-2"
            >
              <Avatar src={user.avatar} name={user.username} size={28} />
              <span className="min-w-0 flex-1 truncate">{user.username}</span>
              <LogOut size={15} /> Sign out
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export function Header() {
  const guilds = useStore((s) => s.guilds);
  const guildId = useStore((s) => s.guildId);
  const player = useStore((s) => s.player);
  const setSearchOpen = useStore((s) => s.setSearchOpen);
  const guild = guilds.find((g) => g.id === guildId);

  return (
    <header className="flex items-center gap-4 px-4 pb-3 pt-[max(0.75rem,env(safe-area-inset-top))] sm:px-6 lg:grid lg:grid-cols-[minmax(0,1fr)_400px] lg:gap-6 lg:px-8 lg:pb-4 lg:pt-6 xl:grid-cols-[minmax(0,1fr)_440px]">
      {/* Desktop: same two columns as the content below, so search lines up with the side panel */}
      <ServerPicker />
      <div className="hidden min-w-0 flex-1 lg:block">
        <h1 className="truncate text-2xl font-bold tracking-tight">{guild?.name ?? "Mugetsu"}</h1>
        {guild && (
          <div className="mt-1 flex items-center gap-3 text-sm text-ink-2">
            <ConnectionDot />
            {player?.voice ? (
              <>
                <span className="truncate">
                  In <span className="font-medium text-ink">{player.voice.channel}</span>
                </span>
                <Listeners listeners={player.voice.listeners} />
              </>
            ) : (
              <span>{player ? "Not in a voice channel" : "Connecting…"}</span>
            )}
          </div>
        )}
      </div>
      <div className="flex-1 lg:hidden" />
      <div className="lg:hidden">
        <ConnectionDot />
      </div>
      <button
        type="button"
        onClick={() => setSearchOpen(true)}
        disabled={!guildId}
        aria-label="Search"
        className="grid size-10 place-items-center rounded-xl bg-panel-2 text-ink-2 disabled:opacity-40 lg:hidden"
      >
        <SearchIcon size={19} />
      </button>
      <div className="hidden w-full lg:block">
        <SearchBox />
      </div>
    </header>
  );
}
