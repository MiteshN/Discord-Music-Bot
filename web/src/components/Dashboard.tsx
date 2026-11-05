import { Headphones, ServerOff } from "lucide-react";
import { useEffect } from "react";
import { useGuildSocket } from "../hooks/useGuildSocket";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useShortcuts } from "../hooks/useShortcuts";
import { splitTitle } from "../lib/format";
import { useStore } from "../store";
import { Header } from "./Header";
import { HistoryList } from "./HistoryList";
import { Lyrics } from "./Lyrics";
import { NowPlaying } from "./NowPlaying";
import { QueueList } from "./QueueList";
import { SearchOverlay } from "./Search";
import { ServerRail } from "./ServerRail";
import { Ambient, Centered, MiniPlayer, MobileNav, PanelTabs, Toasts } from "./Shell";

function PanelBody() {
  const panel = useStore((s) => s.panel);
  if (panel === "lyrics") return <Lyrics />;
  if (panel === "history") return <HistoryList />;
  return <QueueList />;
}

function usePageTitle() {
  const current = useStore((s) => s.player?.current);
  const paused = useStore((s) => s.player?.paused);
  useEffect(() => {
    if (!current) {
      document.title = "Mugetsu";
      return;
    }
    const { name, by } = splitTitle(current.title, current.artist);
    document.title = `${paused ? "❚❚" : "▶"} ${name}${by ? ` · ${by}` : ""} — Mugetsu`;
  }, [current, paused]);
}

function NoServer() {
  const guilds = useStore((s) => s.guilds);
  return guilds.length ? (
    <Centered icon={<Headphones size={34} />} title="Welcome back">
      Pick a server to control its music.
    </Centered>
  ) : (
    <Centered icon={<ServerOff size={34} />} title="No shared servers">
      You aren't in any server this bot is in yet. Invite it to a server, or ask someone to invite you, then sign in again.
    </Centered>
  );
}

export function Dashboard() {
  const guildId = useStore((s) => s.guildId);
  const mobileView = useStore((s) => s.mobileView);
  const refreshGuilds = useStore((s) => s.refreshGuilds);
  const desktop = useMediaQuery("(min-width: 1024px)");

  useGuildSocket(guildId);
  useShortcuts();
  usePageTitle();

  // Keep the "playing" dots on other servers roughly up to date
  useEffect(() => {
    const id = setInterval(() => document.visibilityState === "visible" && refreshGuilds(), 30_000);
    return () => clearInterval(id);
  }, [refreshGuilds]);

  return (
    <div className="relative isolate flex h-full">
      <Ambient />
      <ServerRail />
      <div className="relative flex min-w-0 flex-1 flex-col">
        <Header />
        {!guildId ? (
          <NoServer />
        ) : desktop ? (
          <main className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_400px] gap-6 px-8 pb-6 xl:grid-cols-[minmax(0,1fr)_440px]">
            <div className="scrollbar-thin min-h-0 overflow-y-auto rounded-[28px] border border-line bg-panel px-8 py-8 backdrop-blur-xl">
              <NowPlaying />
            </div>
            <aside className="flex min-h-0 flex-col overflow-hidden rounded-[28px] border border-line bg-panel backdrop-blur-xl">
              <PanelTabs />
              <PanelBody />
            </aside>
          </main>
        ) : (
          <main className="flex min-h-0 flex-1 flex-col">
            {mobileView === "player" ? (
              <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-5 pb-8 pt-2">
                <NowPlaying />
              </div>
            ) : (
              <>
                <h2 className="px-5 pb-2 text-xl font-bold tracking-tight">
                  {{ queue: "Up next", lyrics: "Lyrics", history: "History" }[mobileView]}
                </h2>
                <PanelBody />
                <MiniPlayer />
              </>
            )}
          </main>
        )}
        {guildId && <MobileNav />}
      </div>
      <SearchOverlay />
      <Toasts />
    </div>
  );
}
