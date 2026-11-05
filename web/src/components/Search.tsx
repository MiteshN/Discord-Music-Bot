import { ArrowUpToLine, Link2, Plus, Search as SearchIcon, X } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { api } from "../lib/api";
import { formatTime, isUrl } from "../lib/format";
import { useStore } from "../store";
import type { SearchResults } from "../types";
import { Artwork } from "./ui/Artwork";
import { SourceBadge, Spinner } from "./ui/Buttons";

interface Item {
  key: string;
  query: string;
  title: string;
  meta: string;
  thumb: string;
  source: "spotify" | "youtube";
  label: string;
  wide?: boolean;
}

function flatten(data: SearchResults | null): [string, Item[]][] {
  if (!data) return [];
  const songs: Item[] = data.songs.map((s) => ({
    key: `s${s.url}`,
    query: s.url,
    title: s.name,
    meta: [s.artist, s.duration ? formatTime(s.duration) : ""].filter(Boolean).join(" · "),
    thumb: s.thumbnail,
    source: "spotify",
    label: `${s.name} by ${s.artist}`,
  }));
  const albums: Item[] = data.albums.map((a) => ({
    key: `a${a.url}`,
    query: a.url,
    title: a.title,
    meta: ["Album", a.artist, a.year, a.tracks ? `${a.tracks} songs` : ""].filter(Boolean).join(" · "),
    thumb: a.thumbnail,
    source: "spotify",
    label: `the album ${a.title}`,
  }));
  const videos: Item[] = data.videos.map((v) => ({
    key: `v${v.url}`,
    query: v.url || v.title,
    title: v.title,
    meta: v.duration ? formatTime(v.duration) : "",
    thumb: v.thumbnail,
    source: "youtube",
    label: v.title,
    wide: true,
  }));
  return (
    [
      ["Songs", songs],
      ["Albums", albums],
      ["Videos", videos],
    ] as [string, Item[]][]
  ).filter(([, items]) => items.length);
}

function useSearchResults(query: string) {
  const guildId = useStore((s) => s.guildId);
  const [state, setState] = useState<{ query: string; data: SearchResults | null; loading: boolean }>({
    query: "",
    data: null,
    loading: false,
  });
  const term = query.trim();
  const searchable = !!guildId && term.length >= 2 && !isUrl(term);

  useEffect(() => {
    if (!searchable || !guildId) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setState((s) => ({ ...s, loading: true }));
      api
        .search(guildId, term, controller.signal)
        .then((data) => setState({ query: term, data, loading: false }))
        .catch((err: Error) => {
          if (err.name !== "AbortError") setState({ query: term, data: null, loading: false });
        });
    }, 280);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [guildId, term, searchable]);

  return searchable ? state : { query: "", data: null, loading: false };
}

export function SearchBox({ autoFocus = false, onDone }: { autoFocus?: boolean; onDone?: () => void }) {
  const guildId = useStore((s) => s.guildId);
  const act = useStore((s) => s.act);
  const toast = useStore((s) => s.toast);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(autoFocus);
  const [active, setActive] = useState(-1);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const listId = useId();
  const { data, loading, query: answered } = useSearchResults(query);

  const groups = useMemo(() => flatten(data), [data]);
  const items = useMemo(() => groups.flatMap(([, i]) => i), [groups]);
  const term = query.trim();
  const link = isUrl(term);
  const highlighted = active >= 0 && active < items.length ? active : -1;

  // "/" or Ctrl+K focuses search from anywhere
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      const typing = (e.target as HTMLElement).closest("input, textarea, [contenteditable]");
      if ((e.key === "/" && !typing) || (e.key.toLowerCase() === "k" && (e.ctrlKey || e.metaKey))) {
        if (!input.current || input.current.offsetParent === null) return; // hidden on this layout
        e.preventDefault();
        input.current.focus();
        input.current.select();
        setOpen(true);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    list.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: "nearest" });
  }, [highlighted]);

  const close = () => {
    setOpen(false);
    setActive(-1);
  };

  const add = async (q: string, top: boolean, label?: string) => {
    if (!guildId || !q) return;
    setQuery("");
    close();
    input.current?.blur();
    onDone?.();
    toast(label ? `Adding ${label}${top ? " to play next" : ""}…` : `Adding${top ? " to play next" : ""}…`);
    await act("add", { query: q, top }, { announce: true, key: "add" });
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!items.length) return;
      e.preventDefault();
      setOpen(true);
      const n = items.length;
      setActive((i) => (i < 0 ? (e.key === "ArrowDown" ? 0 : n - 1) : (i + (e.key === "ArrowDown" ? 1 : -1) + n) % n));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const item = highlighted >= 0 ? items[highlighted] : null;
      if (item) add(item.query, e.shiftKey, item.label);
      else if (term) add(term, e.shiftKey);
    } else if (e.key === "Escape") {
      if (query) setQuery("");
      else {
        close();
        input.current?.blur();
        onDone?.();
      }
    }
  };

  const showPanel = open && term.length > 0;
  const noResults = !loading && answered === term && term.length >= 2 && !items.length;
  let index = 0;

  return (
    <div className="relative w-full">
      <div
        className={`flex h-11 items-center gap-2.5 rounded-2xl border px-3.5 transition-colors ${
          open ? "border-accent/50 bg-black/50" : "border-line bg-panel hover:border-line-2"
        }`}
      >
        <SearchIcon size={18} className="shrink-0 text-ink-3" />
        <input
          ref={input}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(-1);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(close, 120)}
          onKeyDown={onKeyDown}
          autoFocus={autoFocus}
          disabled={!guildId}
          placeholder={guildId ? "Search songs, albums, or paste a link" : "Pick a server first"}
          autoComplete="off"
          spellCheck={false}
          enterKeyHint="search"
          role="combobox"
          aria-expanded={showPanel}
          aria-controls={listId}
          aria-activedescendant={highlighted >= 0 ? `${listId}-${highlighted}` : undefined}
          aria-label="Search"
          className="h-full min-w-0 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-3 disabled:cursor-not-allowed"
        />
        {loading && <Spinner size={16} />}
        {query ? (
          <button type="button" onClick={() => setQuery("")} aria-label="Clear search" className="text-ink-3 hover:text-ink">
            <X size={16} />
          </button>
        ) : (
          <kbd className="hidden rounded-md border border-line-2 px-1.5 text-[11px] text-ink-3 sm:block">/</kbd>
        )}
      </div>

      {showPanel && (
        <div
          ref={list}
          id={listId}
          role="listbox"
          onMouseDown={(e) => e.preventDefault()} // keep focus in the input
          className="scrollbar-thin absolute inset-x-0 top-full z-40 mt-2 max-h-[min(70vh,560px)] animate-pop overflow-y-auto rounded-2xl border border-line-2 bg-[#121119]/95 p-1.5 shadow-[0_30px_80px_-20px_rgb(0_0_0/0.9)] backdrop-blur-2xl"
        >
          {link ? (
            <button
              type="button"
              onClick={() => add(term, false)}
              className="flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left hover:bg-panel-2"
            >
              <span className="grid size-10 place-items-center rounded-lg bg-accent/20 text-accent-3">
                <Link2 size={18} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block font-medium">Add this link</span>
                <span className="block truncate text-sm text-ink-3">{term}</span>
              </span>
              <kbd className="text-xs text-ink-3">Enter</kbd>
            </button>
          ) : term.length < 2 ? (
            <p className="px-3 py-4 text-sm text-ink-3">Keep typing…</p>
          ) : noResults ? (
            <div className="px-3 py-4 text-sm text-ink-3">
              No matches. Press <kbd className="text-ink-2">Enter</kbd> to search YouTube for “{term}”.
            </div>
          ) : !items.length ? (
            <div className="flex items-center gap-3 px-3 py-4 text-sm text-ink-3">
              <Spinner size={16} /> Searching…
            </div>
          ) : (
            groups.map(([heading, groupItems]) => (
              <div key={heading} className="py-1">
                <div className="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-ink-3">{heading}</div>
                {groupItems.map((item) => {
                  const i = index++;
                  const isActive = i === highlighted;
                  return (
                    <div
                      key={item.key}
                      id={`${listId}-${i}`}
                      role="option"
                      aria-selected={isActive}
                      data-active={isActive}
                      onMouseEnter={() => setActive(i)}
                      onClick={() => add(item.query, false, item.label)}
                      className={`group flex cursor-pointer items-center gap-3 rounded-xl px-2.5 py-2 ${
                        isActive ? "bg-panel-3" : ""
                      }`}
                    >
                      <Artwork
                        src={item.thumb}
                        url={item.source === "youtube" ? item.query : ""}
                        className={`${item.wide ? "aspect-video w-[72px]" : "size-11"} shrink-0 rounded-lg`}
                        iconSize={16}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[14px] font-medium">{item.title}</div>
                        <div className="mt-0.5 flex items-center gap-2 text-[12.5px] text-ink-3">
                          <SourceBadge source={item.source} />
                          <span className="truncate">{item.meta}</span>
                        </div>
                      </div>
                      <div className={`flex shrink-0 gap-1 ${isActive ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}>
                        <button
                          type="button"
                          title="Play next (Shift+Enter)"
                          onClick={(e) => {
                            e.stopPropagation();
                            add(item.query, true, item.label);
                          }}
                          className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs font-medium text-ink-2 hover:bg-white/10 hover:text-ink"
                        >
                          <ArrowUpToLine size={14} /> Next
                        </button>
                        <button
                          type="button"
                          title="Add to queue (Enter)"
                          onClick={(e) => {
                            e.stopPropagation();
                            add(item.query, false, item.label);
                          }}
                          className="flex items-center gap-1 rounded-lg bg-accent px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-accent-2"
                        >
                          <Plus size={14} /> Add
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            ))
          )}
          {items.length > 0 && (
            <div className="hidden border-t border-line px-3 pb-1 pt-2 text-[11.5px] text-ink-3 sm:block">
              ↑↓ choose · Enter add · Shift+Enter play next · Esc close
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Full-screen search for phones. */
export function SearchOverlay() {
  const open = useStore((s) => s.searchOpen);
  const setOpen = useStore((s) => s.setSearchOpen);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-bg/95 p-4 pt-[max(1rem,env(safe-area-inset-top))] backdrop-blur-xl lg:hidden">
      <div className="flex items-center gap-2">
        <div className="min-w-0 flex-1">
          <SearchBox autoFocus onDone={() => setOpen(false)} />
        </div>
        <button type="button" onClick={() => setOpen(false)} className="px-2 py-2 text-sm font-medium text-ink-2">
          Cancel
        </button>
      </div>
    </div>
  );
}
