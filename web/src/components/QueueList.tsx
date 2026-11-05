import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { ArrowUpToLine, CopyX, Ellipsis, GripVertical, Infinity as InfinityIcon, ListMusic, ListX, Play, RotateCcwClock, Shuffle, UserMinus, Users, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { controls } from "../lib/controls";
import { formatLong, formatTime, plural, splitTitle } from "../lib/format";
import { useStore } from "../store";
import type { Song } from "../types";
import { Artwork } from "./ui/Artwork";
import { Avatar, IconButton } from "./ui/Buttons";

function Row({ song, index }: { song: Song; index: number }) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({
    id: song.id,
  });
  const busy = useStore((s) => s.busy);
  const { name, by } = splitTitle(song.title, song.artist);

  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={`group relative flex items-center gap-3 rounded-xl px-2 py-2 transition-colors ${
        isDragging ? "z-10 bg-[#1b1a24] shadow-2xl ring-1 ring-accent/40" : "hover:bg-panel-2"
      }`}
    >
      <button
        type="button"
        ref={setActivatorNodeRef}
        {...attributes}
        {...listeners}
        aria-label={`Reorder ${name}`}
        className="relative grid w-6 shrink-0 cursor-grab touch-none place-items-center text-ink-3 active:cursor-grabbing"
      >
        <span className="text-xs tabular group-hover:opacity-0 pointer-coarse:opacity-0">{index + 1}</span>
        <GripVertical size={16} className="absolute opacity-0 group-hover:opacity-100 pointer-coarse:opacity-100" />
      </button>
      <Artwork src={song.thumbnail} url={song.url} className="size-11 shrink-0 rounded-lg" iconSize={16} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[14px] font-medium leading-snug">{name}</div>
        <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[12.5px] text-ink-3">
          {by && <span className="truncate">{by}</span>}
          {by && <span aria-hidden>·</span>}
          <span className="shrink-0 tabular">{song.live ? "Live" : song.duration ? formatTime(song.duration) : "–:––"}</span>
          <Avatar src={song.requester_avatar} name={`Added by ${song.requester}`} size={14} className="ml-0.5" />
        </div>
      </div>
      <div className="flex max-w-0 shrink-0 items-center overflow-hidden group-focus-within:max-w-40 group-hover:max-w-40 pointer-coarse:max-w-none">
        <IconButton label="Play now" size="sm" busy={busy[`skipto:${song.id}`]} onClick={() => controls.skipTo(song.id)}>
          <Play size={15} fill="currentColor" />
        </IconButton>
        {index > 0 && (
          <IconButton label="Play next" size="sm" className="pointer-coarse:hidden" onClick={() => controls.move(song.id, 0)}>
            <ArrowUpToLine size={16} />
          </IconButton>
        )}
        <IconButton label="Remove" size="sm" tone="danger" onClick={() => controls.remove(song.id)}>
          <X size={16} />
        </IconButton>
      </div>
    </li>
  );
}

function MenuItem({ icon, children, onClick, disabled }: { icon: ReactNode; children: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="menuitem"
      disabled={disabled}
      onClick={onClick}
      className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm text-ink-2 hover:bg-panel-3 hover:text-ink disabled:opacity-40"
    >
      <span className="text-ink-3">{icon}</span>
      {children}
    </button>
  );
}

function QueueMenu({ total }: { total: number }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

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

  const run = (fn: () => void) => () => {
    setOpen(false);
    fn();
  };

  return (
    <div ref={ref} className="relative">
      <IconButton label="More queue actions" size="sm" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Ellipsis size={17} />
      </IconButton>
      {open && (
        <div role="menu" className="absolute right-0 top-full z-30 mt-1.5 w-64 animate-pop rounded-2xl border border-line-2 bg-[#15141d]/95 p-1.5 shadow-[0_24px_60px_-15px_rgb(0_0_0/0.9)] backdrop-blur-2xl">
          <MenuItem icon={<CopyX size={16} />} disabled={total < 2} onClick={run(controls.removeDuplicates)}>
            Remove duplicates
          </MenuItem>
          <MenuItem icon={<Users size={16} />} disabled={!total} onClick={run(controls.removeAbsent)}>
            Remove songs from people who left
          </MenuItem>
          <MenuItem icon={<UserMinus size={16} />} disabled={!total} onClick={run(controls.removeMine)}>
            Remove my songs
          </MenuItem>
          <div className="my-1 h-px bg-line" />
          <MenuItem icon={<RotateCcwClock size={16} />} onClick={run(() => controls.playRecent(10))}>
            Queue my recent songs
          </MenuItem>
        </div>
      )}
    </div>
  );
}

export function QueueList() {
  const player = useStore((s) => s.player);
  const [confirmClear, setConfirmClear] = useState(false);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  if (!player) return null;
  const { queue, queue_length: total } = player;

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    const to = queue.findIndex((s) => s.id === over.id);
    if (to >= 0) controls.move(Number(active.id), to);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between gap-3 px-5 pb-3 pt-1">
        <p className="text-sm text-ink-2">
          {total ? (
            <>
              {plural(total, "track")}
              {player.queue_duration > 0 && <span className="text-ink-3"> · {formatLong(player.queue_duration)}</span>}
            </>
          ) : (
            "Nothing queued"
          )}
        </p>
        <div className="flex gap-1">
          <IconButton
            label={player.autoplay ? "Autoplay is on: similar songs play when the queue runs out" : "Autoplay: keep playing similar songs when the queue runs out"}
            size="sm"
            active={player.autoplay}
            onClick={() => controls.setAutoplay(!player.autoplay)}
          >
            <InfinityIcon size={17} />
          </IconButton>
          <IconButton label="Shuffle queue" size="sm" disabled={total < 2} onClick={controls.shuffle}>
            <Shuffle size={16} />
          </IconButton>
          <IconButton
            label={confirmClear ? "Click again to clear the queue" : "Clear queue"}
            size="sm"
            tone="danger"
            disabled={!total}
            className={confirmClear ? "!bg-danger/20 !text-danger" : ""}
            onClick={() => {
              if (confirmClear) {
                setConfirmClear(false);
                controls.clear();
              } else {
                setConfirmClear(true);
                setTimeout(() => setConfirmClear(false), 3000);
              }
            }}
          >
            <ListX size={17} />
          </IconButton>
          <QueueMenu total={total} />
        </div>
      </div>

      {total === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-8 pb-12 text-center text-ink-3">
          <span className="grid size-14 place-items-center rounded-2xl bg-panel-2">
            <ListMusic size={24} />
          </span>
          <p className="text-[15px] font-medium text-ink-2">Your queue is empty</p>
          <p className="text-sm">
            {player.autoplay
              ? "Autoplay is on, so similar songs will follow whatever plays next."
              : "Search for songs, albums or paste a playlist link to fill it up. Or turn on autoplay (∞) to keep the music going."}
          </p>
        </div>
      ) : (
        <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-3 pb-4">
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
            <SortableContext items={queue.map((s) => s.id)} strategy={verticalListSortingStrategy}>
              <ol className="flex flex-col gap-0.5">
                {queue.map((song, i) => (
                  <Row key={song.id} song={song} index={i} />
                ))}
              </ol>
            </SortableContext>
          </DndContext>
          {total > queue.length && (
            <p className="px-3 pt-3 text-center text-sm text-ink-3">+ {plural(total - queue.length, "more track")}</p>
          )}
        </div>
      )}
    </div>
  );
}
