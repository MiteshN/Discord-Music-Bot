import { LogOut } from "lucide-react";
import { useState } from "react";
import { initials } from "../lib/format";
import { useStore } from "../store";
import type { Guild } from "../types";
import { Logo } from "./Logo";

export function GuildIcon({ guild, className = "size-12" }: { guild: Guild; className?: string }) {
  const [broken, setBroken] = useState(false);
  return guild.icon && !broken ? (
    <img
      src={guild.icon}
      alt=""
      className={`object-cover ${className}`}
      referrerPolicy="no-referrer"
      onError={() => setBroken(true)}
    />
  ) : (
    <span className={`grid place-items-center bg-panel-3 text-sm font-semibold text-ink-2 ${className}`}>
      {initials(guild.name)}
    </span>
  );
}

/** Discord-style column of servers. Desktop only; phones use the server picker in the header. */
export function ServerRail() {
  const guilds = useStore((s) => s.guilds);
  const guildId = useStore((s) => s.guildId);
  const selectGuild = useStore((s) => s.selectGuild);
  const user = useStore((s) => s.user);
  const signOut = useStore((s) => s.signOut);

  return (
    <aside className="hidden w-[76px] shrink-0 flex-col items-center gap-3 border-r border-line bg-black/30 py-4 backdrop-blur-xl lg:flex">
      <Logo className="size-11" />
      <div className="h-px w-8 bg-line-2" />
      <nav aria-label="Servers" className="scrollbar-thin flex min-h-0 flex-1 flex-col items-center gap-2.5 overflow-y-auto px-3 py-1">
        {guilds.map((g) => {
          const active = g.id === guildId;
          return (
            <button
              key={g.id}
              type="button"
              onClick={() => selectGuild(g.id)}
              aria-label={g.name}
              aria-current={active || undefined}
              className="group relative"
            >
              <span
                className={`absolute -left-3 top-1/2 w-1 -translate-y-1/2 rounded-r-full bg-ink transition-all ${
                  active ? "h-9" : g.playing ? "h-2" : "h-0 group-hover:h-5"
                }`}
              />
              <GuildIcon
                guild={g}
                className={`size-12 transition-all duration-200 ${
                  active ? "rounded-2xl ring-2 ring-accent/70" : "rounded-[24px] group-hover:rounded-2xl"
                }`}
              />
              {g.playing && (
                <span className="absolute -bottom-0.5 -right-0.5 grid size-[18px] place-items-center rounded-full border-[3px] border-bg bg-success">
                  <span className="sr-only">Playing</span>
                </span>
              )}
              <span className="pointer-events-none absolute left-full top-1/2 z-50 ml-4 -translate-y-1/2 whitespace-nowrap rounded-lg bg-black/90 px-3 py-1.5 text-sm font-medium opacity-0 shadow-xl transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
                {g.name}
              </span>
            </button>
          );
        })}
      </nav>
      {user && (
        <div className="group relative">
          <img src={user.avatar} alt="" referrerPolicy="no-referrer" className="size-10 rounded-full bg-panel-3 object-cover" />
          <button
            type="button"
            onClick={signOut}
            className="absolute inset-0 grid place-items-center rounded-full bg-black/70 opacity-0 transition-opacity focus:opacity-100 group-hover:opacity-100"
            aria-label={`Signed in as ${user.username}. Sign out`}
            title={`${user.username} · Sign out`}
          >
            <LogOut size={16} />
          </button>
        </div>
      )}
    </aside>
  );
}
