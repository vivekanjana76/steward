// A small geometric shield/sigil for Steward — a hexagonal "guardian" mark with
// a check, rendered with a cyan→violet gradient stroke.

export function BrandMark({ size = 34 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      role="img"
      aria-label="Steward"
    >
      <defs>
        <linearGradient id="steward-mark" x1="6" y1="4" x2="42" y2="44" gradientUnits="userSpaceOnUse">
          <stop stopColor="#22d3ee" />
          <stop offset="1" stopColor="#8b5cf6" />
        </linearGradient>
      </defs>
      <path
        d="M24 4 6 12v12c0 11 7.5 17.5 18 20 10.5-2.5 18-9 18-20V12L24 4Z"
        stroke="url(#steward-mark)"
        strokeWidth="2"
        strokeLinejoin="round"
        fill="rgba(34,211,238,0.06)"
      />
      <path
        d="m16 24 6 6 11-12"
        stroke="url(#steward-mark)"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
