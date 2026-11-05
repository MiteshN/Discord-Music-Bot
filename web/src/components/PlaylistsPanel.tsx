import { Check, ChevronDown, Copy, Library, Pencil, Play, Save, Share2, Shuffle, Trash, X } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { controls } from "../lib/controls";
import { formatLong, formatTime, plural, splitTitle } from "../lib/format";
import { useStore } from "../store";
import type { Playlist } from "../types";
import { Artwork } from "./ui/Artwork";
import { IconButton, Spinner } from "./ui/Buttons";

function NameForm({ placeholder, initial = "", submit, onCancel, icon = "save" }: {
  placeholder: string;
  initial?: string;
  submit: (name: string) => void;
  onCancel?: () => void;
  icon?: "save" | "check";
}) {
  const [name, setName] = useState(initial);
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim()) submit(name.trim());
  };
  return (
    <form onSubmit={onSubmit} className="flex items-center gap-1.5">
      <input
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => e.key === "Escape" && onCancel?.()}
        placeholder={placeholder}
        maxLength={100}
        className="h-9 min-w-0 flex-1 rounded-xl border border-line-2 bg-black/30 px-3 text-sm outline-none placeholder:text-ink-3 focus:border-accent/60"
      />
      <IconButton label={icon === "save" ? "Save" : "Done"} size="sm" type="submit" disabled={!name.trim()}>
        {icon === "save" ? <Save size={16} /> : <Check size={16} />}
      </IconButton>
      {onCancel && (
        <IconButton label="Cancel" size="sm" onClick={onCancel}>
          <X size={16} />
        </IconButton>
      )}
    </form>
  );
}

function PlaylistRow({ playlist }: { playlist: Playlist }) {
  const playlistAction = useStore((s) => s.playlistAction);
  const toast = useStore((s) => s.toast);
  const busy = useStore((s) => s.busy[`load:${playlist.name}`]);
  const [open, setOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const covers = playlist.tracks.slice(0, 4).map((t) => t.thumbnail);

  const share = async () => {
    const code = await playlistAction("share", { name: playlist.name });
    if (!code) return;
    try {
      await navigator.clipboard.writeText(code);
      toast(`Share code ${code} copied. Anyone can load it with /playlist load ${code}`, "success");
    } catch {
      toast(`Share code: ${code}`, "info");
    }
  };

  return (
    <li className="rounded-2xl border border-line bg-panel">
      <div className="group flex items-center gap-3 p-2.5">
        <button type="button" onClick={() => setOpen((o) => !o)} className="flex min-w-0 flex-1 items-center gap-3 text-left" aria-expanded={open}>
          <div className="grid size-12 shrink-0 grid-cols-2 overflow-hidden rounded-xl bg-panel-3">
            {covers.length >= 4 ? (
              covers.map((c, i) => <Artwork key={i} src={c} className="size-6" iconSize={8} />)
            ) : (
              <Artwork src={covers[0] ?? ""} className="col-span-2 row-span-2 size-12" iconSize={18} />
            )}
          </div>
          <span className="min-w-0 flex-1">
            {renaming ? null : <span className="block truncate text-[14px] font-semibold">{playlist.name}</span>}
            <span className="block truncate text-[12.5px] text-ink-3">
              {plural(playlist.count, "song")}
              {playlist.duration > 0 && ` · ${formatLong(playlist.duration)}`}
              {playlist.share_code && ` · code ${playlist.share_code}`}
            </span>
          </span>
          <ChevronDown size={16} className={`shrink-0 text-ink-3 transition-transform ${open ? "rotate-180" : ""}`} />
        </button>
        <IconButton label="Play" size="sm" busy={busy} disabled={!playlist.count} onClick={() => controls.loadPlaylist(playlist.name)}>
          <Play size={15} fill="currentColor" />
        </IconButton>
        <IconButton label="Shuffle play" size="sm" disabled={!playlist.count} onClick={() => controls.loadPlaylist(playlist.name, true)}>
          <Shuffle size={15} />
        </IconButton>
      </div>
      {renaming && (
        <div className="px-3 pb-3">
          <NameForm
            placeholder="New name"
            initial={playlist.name}
            icon="check"
            onCancel={() => setRenaming(false)}
            submit={async (name) => {
              if (name !== playlist.name) await playlistAction("rename", { name: playlist.name, new_name: name }, "");
              setRenaming(false);
            }}
          />
        </div>
      )}
      {open && (
        <div className="border-t border-line px-2 pb-2 pt-1">
          <div className="flex items-center gap-1 px-1 py-1.5">
            <button type="button" onClick={share} className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-medium text-ink-2 hover:bg-panel-2 hover:text-ink">
              {playlist.share_code ? <Copy size={14} /> : <Share2 size={14} />} {playlist.share_code ? "Copy code" : "Share"}
            </button>
            <button type="button" onClick={() => setRenaming(true)} className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-medium text-ink-2 hover:bg-panel-2 hover:text-ink">
              <Pencil size={14} /> Rename
            </button>
            <button
              type="button"
              onClick={() => {
                if (confirmDelete) playlistAction("delete", { name: playlist.name }, "");
                else {
                  setConfirmDelete(true);
                  setTimeout(() => setConfirmDelete(false), 3000);
                }
              }}
              className={`ml-auto flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-medium ${
                confirmDelete ? "bg-danger/20 text-danger" : "text-ink-3 hover:bg-danger/10 hover:text-danger"
              }`}
            >
              <Trash size={14} /> {confirmDelete ? "Click again to delete" : "Delete"}
            </button>
          </div>
          <ol className="scrollbar-thin max-h-72 overflow-y-auto">
            {playlist.tracks.map((t, i) => {
              const { name, by } = splitTitle(t.title, t.artist);
              return (
                <li key={`${i}-${t.title}`} className="group flex items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-panel-2">
                  <span className="w-5 shrink-0 text-right text-xs text-ink-3 tabular">{i + 1}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px]">{name}</span>
                    {by && <span className="block truncate text-[11.5px] text-ink-3">{by}</span>}
                  </span>
                  {t.duration > 0 && <span className="text-[11.5px] text-ink-3 tabular">{formatTime(t.duration)}</span>}
                  <button
                    type="button"
                    aria-label={`Remove ${name}`}
                    title="Remove from playlist"
                    onClick={() => playlistAction("removetrack", { name: playlist.name, index: i }, "")}
                    className="grid size-6 place-items-center rounded-md text-ink-3 opacity-0 hover:bg-danger/12 hover:text-danger group-hover:opacity-100 pointer-coarse:opacity-100"
                  >
                    <X size={14} />
                  </button>
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </li>
  );
}

export function PlaylistsPanel() {
  const playlists = useStore((s) => s.playlists);
  const loadPlaylists = useStore((s) => s.loadPlaylists);
  const hasQueue = useStore((s) => !!s.player && (!!s.player.current || s.player.queue_length > 0) && !s.player.game);
  const [saving, setSaving] = useState(false);
  const [code, setCode] = useState("");

  useEffect(() => {
    loadPlaylists();
  }, [loadPlaylists]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="space-y-2 px-4 pb-3 pt-1">
        {saving ? (
          <NameForm
            placeholder="Name this playlist"
            onCancel={() => setSaving(false)}
            submit={async (name) => {
              await controls.saveQueue(name);
              setSaving(false);
            }}
          />
        ) : (
          <button
            type="button"
            onClick={() => setSaving(true)}
            disabled={!hasQueue}
            className="flex h-9 w-full items-center justify-center gap-2 rounded-xl bg-accent/15 text-sm font-semibold text-accent-3 transition-colors hover:bg-accent/25 disabled:opacity-40"
          >
            <Save size={16} /> Save current queue as a playlist
          </button>
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (code.trim()) {
              controls.loadPlaylist(code.trim());
              setCode("");
            }
          }}
          className="flex gap-1.5"
        >
          <input
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            placeholder="Got a share code? Paste it to play"
            maxLength={8}
            className="h-9 min-w-0 flex-1 rounded-xl border border-line bg-panel px-3 text-sm uppercase tracking-wider outline-none placeholder:normal-case placeholder:tracking-normal placeholder:text-ink-3 focus:border-accent/60"
          />
          <IconButton label="Play shared playlist" size="sm" type="submit" disabled={code.trim().length !== 8}>
            <Play size={15} fill="currentColor" />
          </IconButton>
        </form>
      </div>
      {playlists === null ? (
        <div className="flex flex-1 items-center justify-center">
          <Spinner />
        </div>
      ) : playlists.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-8 pb-12 text-center text-ink-3">
          <span className="grid size-14 place-items-center rounded-2xl bg-panel-2">
            <Library size={24} />
          </span>
          <p className="text-[15px] font-medium text-ink-2">No playlists yet</p>
          <p className="text-sm">Save the queue above, or tap ♥ › Add to playlist on any song. They work in every server.</p>
        </div>
      ) : (
        <ul className="scrollbar-thin min-h-0 flex-1 space-y-2 overflow-y-auto px-3 pb-4">
          {playlists.map((p) => (
            <PlaylistRow key={p.name} playlist={p} />
          ))}
        </ul>
      )}
    </div>
  );
}
