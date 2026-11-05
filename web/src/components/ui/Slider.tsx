import { useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

interface SliderProps {
  value: number;
  max: number;
  label: string;
  /** Called on release (or after keyboard input settles). */
  onCommit: (value: number) => void;
  /** Called continuously while dragging. */
  onPreview?: (value: number | null) => void;
  format?: (value: number) => string;
  disabled?: boolean;
  step?: number;
  className?: string;
  /** Show the hovered position in a bubble above the bar. */
  hoverTip?: boolean;
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export function Slider({
  value,
  max,
  label,
  onCommit,
  onPreview,
  format = String,
  disabled = false,
  step = 1,
  className = "",
  hoverTip = false,
}: SliderProps) {
  const track = useRef<HTMLDivElement>(null);
  const keyTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const [drag, setDrag] = useState<number | null>(null);
  const [hover, setHover] = useState<{ x: number; value: number } | null>(null);
  // After a commit, keep showing the chosen value until the real one catches up
  const [hold, setHold] = useState<{ value: number; base: number } | null>(null);

  const held = hold && hold.base === value ? hold.value : null;
  const shown = drag ?? held ?? value;
  const pct = max > 0 ? clamp((shown / max) * 100, 0, 100) : 0;

  const valueAt = (clientX: number) => {
    const rect = track.current!.getBoundingClientRect();
    const ratio = clamp((clientX - rect.left) / rect.width, 0, 1);
    return clamp(Math.round((ratio * max) / step) * step, 0, max);
  };

  const preview = (v: number | null) => {
    setDrag(v);
    onPreview?.(v);
  };

  const commit = (v: number) => {
    preview(null);
    setHold({ value: v, base: value });
    setTimeout(() => setHold(null), 2500);
    onCommit(v);
  };

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (disabled || e.button !== 0) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    preview(valueAt(e.clientX));
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (disabled) return;
    if (hoverTip && e.pointerType === "mouse") {
      const rect = track.current!.getBoundingClientRect();
      setHover({ x: clamp(e.clientX - rect.left, 0, rect.width), value: valueAt(e.clientX) });
    }
    if (drag !== null) preview(valueAt(e.clientX));
  };
  const onPointerUp = (e: PointerEvent<HTMLDivElement>) => {
    if (drag === null) return;
    commit(valueAt(e.clientX));
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (disabled) return;
    const big = Math.max(step, Math.round(max / 10));
    const deltas: Record<string, number> = {
      ArrowRight: step * (e.shiftKey ? 10 : 1),
      ArrowUp: step * (e.shiftKey ? 10 : 1),
      ArrowLeft: -step * (e.shiftKey ? 10 : 1),
      ArrowDown: -step * (e.shiftKey ? 10 : 1),
      PageUp: big,
      PageDown: -big,
    };
    let next: number | null = null;
    if (e.key in deltas) next = clamp(shown + deltas[e.key], 0, max);
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = max;
    if (next === null) return;
    e.preventDefault();
    e.stopPropagation();
    preview(next);
    clearTimeout(keyTimer.current);
    const settled = next;
    keyTimer.current = setTimeout(() => commit(settled), 400);
  };

  return (
    <div
      role="slider"
      tabIndex={disabled ? -1 : 0}
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={Math.round(shown)}
      aria-valuetext={format(shown)}
      aria-disabled={disabled}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={() => preview(null)}
      onPointerLeave={() => setHover(null)}
      onKeyDown={onKeyDown}
      className={`group relative flex h-5 touch-none select-none items-center ${
        disabled ? "opacity-40" : "cursor-pointer"
      } ${className}`}
    >
      <div ref={track} className="relative h-1 w-full rounded-full bg-white/12 transition-[height] group-hover:h-1.5">
        <div
          className={`absolute inset-y-0 left-0 rounded-full ${
            drag !== null ? "bg-accent-2" : "bg-ink group-hover:bg-accent-2"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div
        className={`pointer-events-none absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white shadow-[0_2px_8px_rgb(0_0_0/0.5)] transition-opacity ${
          drag !== null ? "opacity-100" : "opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100"
        }`}
        style={{ left: `${pct}%` }}
      />
      {hoverTip && hover && !disabled && (
        <div
          className="pointer-events-none absolute -top-8 -translate-x-1/2 rounded-md bg-black/85 px-2 py-0.5 text-xs tabular text-ink shadow-lg"
          style={{ left: hover.x }}
        >
          {format(drag ?? hover.value)}
        </div>
      )}
    </div>
  );
}
