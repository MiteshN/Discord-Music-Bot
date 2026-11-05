import { LoaderCircle } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Size = "sm" | "md" | "lg";

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
  size?: Size;
  active?: boolean;
  busy?: boolean;
  tone?: "default" | "danger";
  children: ReactNode;
}

const sizes: Record<Size, string> = {
  sm: "size-8 rounded-lg",
  md: "size-10 rounded-xl",
  lg: "size-12 rounded-2xl",
};

export function IconButton({
  label,
  size = "md",
  active = false,
  busy = false,
  tone = "default",
  className = "",
  children,
  disabled,
  ...rest
}: IconButtonProps) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={active || undefined}
      disabled={disabled || busy}
      className={`relative grid shrink-0 place-items-center transition-colors duration-150 disabled:opacity-35 ${sizes[size]} ${
        active
          ? "bg-accent/20 text-accent-3 hover:bg-accent/28"
          : tone === "danger"
            ? "text-ink-2 hover:bg-danger/12 hover:text-danger"
            : "text-ink-2 hover:bg-panel-3 hover:text-ink"
      } ${className}`}
      {...rest}
    >
      {busy ? <LoaderCircle className="animate-spin" size={18} /> : children}
    </button>
  );
}

export function Spinner({ size = 18, className = "" }: { size?: number; className?: string }) {
  return <LoaderCircle size={size} className={`animate-spin text-ink-3 ${className}`} aria-label="Loading" />;
}

export function Eq({ paused = false, className = "" }: { paused?: boolean; className?: string }) {
  return (
    <span className={`eq ${paused ? "paused" : ""} ${className}`} aria-hidden>
      <i />
      <i />
      <i />
      <i />
    </span>
  );
}

export function Avatar({ src, name, size = 24, className = "" }: { src: string; name: string; size?: number; className?: string }) {
  return src ? (
    <img
      src={src}
      alt=""
      title={name}
      width={size}
      height={size}
      loading="lazy"
      referrerPolicy="no-referrer"
      className={`shrink-0 rounded-full bg-panel-3 object-cover ${className}`}
      style={{ width: size, height: size }}
    />
  ) : (
    <span
      title={name}
      className={`grid shrink-0 place-items-center rounded-full bg-accent/30 text-[10px] font-semibold ${className}`}
      style={{ width: size, height: size }}
    >
      {[...name][0]?.toUpperCase()}
    </span>
  );
}

const SOURCE_STYLES: Record<string, { label: string; className: string }> = {
  spotify: { label: "Spotify", className: "text-spotify bg-spotify/10" },
  youtube: { label: "YouTube", className: "text-youtube bg-youtube/10" },
  soundcloud: { label: "SoundCloud", className: "text-soundcloud bg-soundcloud/10" },
  bandcamp: { label: "Bandcamp", className: "text-sky-300 bg-sky-300/10" },
  web: { label: "Web", className: "text-ink-2 bg-panel-3" },
};

export function SourceBadge({ source }: { source: string }) {
  const style = SOURCE_STYLES[source] ?? SOURCE_STYLES.web;
  return (
    <span className={`rounded px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide ${style.className}`}>
      {style.label}
    </span>
  );
}
