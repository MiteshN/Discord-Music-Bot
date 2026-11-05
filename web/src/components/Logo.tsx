/** The crescent-moon mark (Mugetsu means "moonless night"). */
export function Logo({ className = "size-10" }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={`rounded-[30%] ${className}`} aria-hidden>
      <defs>
        <linearGradient id="mugetsu-logo" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#a78bfa" />
          <stop offset="1" stopColor="#6d28d9" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="18" fill="url(#mugetsu-logo)" />
      <path d="M40 14a18 18 0 1 0 10.6 32.6A15 15 0 1 1 40 14z" fill="#fff" opacity=".95" />
      <circle cx="45" cy="21" r="2.4" fill="#fff" opacity=".8" />
    </svg>
  );
}
