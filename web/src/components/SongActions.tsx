import { Check, Heart, ListPlus, Plus } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { controls } from "../lib/controls";
import { useStore } from "../store";
import { Spinner } from "./ui/Buttons";

/** ♥ to DMs and "add to playlist", under the now-playing title. */
export function SongActions() {
  const playlists = useStore((s) => s.playlists);
  const loadPlaylists = useStore((s) => s.loadPlaylists);
  const busy = useStore((s) => s.busy);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    loadPlaylists();
    const onDown = (e: PointerEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, loadPlaylists]);

  const add = async (target: string) => {
    setOpen(false);
    setName("");
    await controls.addCurrentTo(target);
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim()) add(name.trim());
  };

  const round = "grid size-7 place-items-center rounded-full bg-panel-2 text-ink-2 transition-colors hover:bg-panel-3 hover:text-ink";

  return (
    <div ref={ref} className="relative flex items-center gap-2">
      <button type="button" onClick={controls.saveToDMs} disabled={busy.save} className={`${round} hover:!text-pink-300`} title="Save to your DMs" aria-label="Save this song to your DMs">
        {busy.save ? <Spinner size={13} /> : <Heart size={14} />}
      </button>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-haspopup="menu" className={round} title="Add to playlist" aria-label="Add this song to a playlist">
        <ListPlus size={15} />
      </button>
      {open && (
        <div role="menu" className="absolute left-1/2 top-full z-30 mt-2 w-72 -translate-x-1/2 animate-pop rounded-2xl border border-line-2 bg-[#15141d]/95 p-2 text-left shadow-[0_24px_60px_-15px_rgb(0_0_0/0.9)] backdrop-blur-2xl">
          <div className="px-2 pb-1.5 pt-1 text-xs font-semibold uppercase tracking-[0.14em] text-ink-3">Add to playlist</div>
          <div className="scrollbar-thin max-h-56 overflow-y-auto">
            {playlists === null ? (
              <div className="flex justify-center py-3">
                <Spinner size={16} />
              </div>
            ) : (
              playlists.map((p) => (
                <button
                  key={p.name}
                  type="button"
                  role="menuitem"
                  onClick={() => add(p.name)}
                  className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm hover:bg-panel-3"
                >
                  <span className="min-w-0 flex-1 truncate">{p.name}</span>
                  <span className="text-xs text-ink-3 tabular">{p.count}</span>
                  {busy[`savecurrent:${p.name}`] && <Check size={14} className="text-success" />}
                </button>
              ))
            )}
          </div>
          <form onSubmit={submit} className="mt-1.5 flex gap-1.5 border-t border-line pt-2">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="New playlist…"
              maxLength={100}
              className="h-8 min-w-0 flex-1 rounded-lg border border-line bg-black/30 px-2.5 text-sm outline-none placeholder:text-ink-3 focus:border-accent/60"
            />
            <button type="submit" disabled={!name.trim()} aria-label="Create and add" className="grid size-8 place-items-center rounded-lg bg-accent text-white disabled:opacity-40">
              <Plus size={16} />
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
