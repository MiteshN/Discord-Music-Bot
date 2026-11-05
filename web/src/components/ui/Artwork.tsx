import { EighthNotes } from "lucide-react";
import { useState } from "react";
import { youtubeThumb } from "../../lib/format";

interface ArtworkProps {
  src: string;
  url?: string;
  alt?: string;
  className?: string;
  iconSize?: number;
  /** "eager" for the big now-playing cover */
  loading?: "lazy" | "eager";
}

/** Cover art that falls back to the YouTube thumbnail, then to a placeholder. */
export function Artwork(props: ArtworkProps) {
  // Re-mount when the image changes so a failure on one track never sticks to the next
  return <ArtworkInner key={`${props.src}|${props.url ?? ""}`} {...props} />;
}

function ArtworkInner({ src, url = "", alt = "", className = "", iconSize = 22, loading = "lazy" }: ArtworkProps) {
  const candidates = [src, youtubeThumb(url)].filter((c, i, all) => c && all.indexOf(c) === i);
  const [index, setIndex] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const current = candidates[index];

  return (
    <div className={`relative overflow-hidden bg-linear-to-br from-accent/25 via-panel-2 to-panel ${className}`}>
      {!loaded && (
        <div className="absolute inset-0 grid place-items-center text-ink-3">
          <EighthNotes size={iconSize} strokeWidth={1.6} />
        </div>
      )}
      {current && (
        <img
          src={current}
          alt={alt}
          loading={loading}
          decoding="async"
          referrerPolicy="no-referrer"
          draggable={false}
          onLoad={() => setLoaded(true)}
          onError={() => {
            setLoaded(false);
            setIndex((i) => i + 1);
          }}
          className={`absolute inset-0 size-full object-cover transition-opacity duration-500 ${
            loaded ? "opacity-100" : "opacity-0"
          }`}
        />
      )}
    </div>
  );
}
