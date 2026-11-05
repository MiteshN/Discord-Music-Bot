import { useId } from "react";

/** A crescent moon and a star on a night-sky tile (Mugetsu means "moonless night"). */
export function Logo({ className = "size-10" }: { className?: string }) {
  // Unique ids: the logo appears more than once on some screens
  const id = `logo${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const bg = `${id}-bg`;
  const ink = `${id}-ink`;
  const cut = `${id}-cut`;
  return (
    <svg viewBox="0 0 64 64" className={`shrink-0 rounded-[25%] ${className}`} aria-hidden>
      <defs>
        <linearGradient id={bg} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#2a1d4f" />
          <stop offset="1" stopColor="#0e0b1a" />
        </linearGradient>
        <linearGradient id={ink} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#fff" />
          <stop offset="1" stopColor="#ddd6fe" />
        </linearGradient>
        <mask id={cut}>
          <circle cx="31" cy="33" r="17" fill="#fff" />
          <circle cx="37.5" cy="27.5" r="15" fill="#000" />
        </mask>
      </defs>
      <rect width="64" height="64" rx="16" fill={`url(#${bg})`} />
      <rect width="64" height="64" fill={`url(#${ink})`} mask={`url(#${cut})`} />
      <path d="M44 15.5 L45.3 19.7 L49.5 21 L45.3 22.3 L44 26.5 L42.7 22.3 L38.5 21 L42.7 19.7 Z" fill="#c4b5fd" />
      <circle cx="50" cy="31" r="1.3" fill="#a78bfa" />
      <rect x=".5" y=".5" width="63" height="63" rx="15.5" fill="none" stroke="#fff" strokeOpacity=".1" />
    </svg>
  );
}
