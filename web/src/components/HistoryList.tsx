import { ArrowUpToLine, Plus, RotateCcwClock } from "lucide-react";
import { controls } from "../lib/controls";
import { formatTime, splitTitle } from "../lib/format";
import { useStore } from "../store";
import { Artwork } from "./ui/Artwork";
import { IconButton } from "./ui/Buttons";

function RecentButton() {
  const busy = useStore((s) => s.busy.playrecent);
  return (
    <button
      type="button"
      onClick={() => controls.playRecent(10)}
      disabled={busy}
      className="mt-1 inline-flex items-center gap-2 rounded-xl border border-line px-3 py-2 text-sm font-medium text-ink-2 transition-colors hover:border-line-2 hover:bg-panel-2 hover:text-ink disabled:opacity-50"
    >
      <RotateCcwClock size={15} /> Queue my 10 most recent requests
    </button>
  );
}

export function HistoryList() {
  const history = useStore((s) => s.player?.history ?? []);
  const busy = useStore((s) => s.busy.add);

  if (!history.length) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 px-8 pb-12 text-center text-ink-3">
        <span className="grid size-14 place-items-center rounded-2xl bg-panel-2">
          <RotateCcwClock size={24} />
        </span>
        <p className="text-[15px] font-medium text-ink-2">Nothing played yet</p>
        <p className="text-sm">Songs show up here after they play, so you can bring them back.</p>
        <RecentButton />
      </div>
    );
  }

  return (
    <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-3 pb-4">
      <div className="px-1 pb-2">
        <RecentButton />
      </div>
      <ol className="flex flex-col gap-0.5">
        {history.map((song, i) => {
          const { name, by } = splitTitle(song.title, song.artist);
          const query = song.url || song.title;
          return (
            <li key={`${song.id}-${i}`} className="group flex items-center gap-3 rounded-xl px-2 py-2 hover:bg-panel-2">
              <Artwork src={song.thumbnail} url={song.url} className="size-11 shrink-0 rounded-lg opacity-80" iconSize={16} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[14px] font-medium text-ink-2 group-hover:text-ink">{name}</div>
                <div className="mt-0.5 truncate text-[12.5px] text-ink-3">
                  {[by, song.duration ? formatTime(song.duration) : "", `added by ${song.requester}`].filter(Boolean).join(" · ")}
                </div>
              </div>
              <div className="flex max-w-0 shrink-0 items-center overflow-hidden group-focus-within:max-w-40 group-hover:max-w-40 pointer-coarse:max-w-none">
                <IconButton label="Play next" size="sm" disabled={busy} onClick={() => controls.add(query, true)}>
                  <ArrowUpToLine size={16} />
                </IconButton>
                <IconButton label="Add to queue" size="sm" disabled={busy} onClick={() => controls.add(query)}>
                  <Plus size={17} />
                </IconButton>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
