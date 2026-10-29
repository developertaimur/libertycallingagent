"use client";

/** Deterministic mini sparkline from a seed value (no Math.random — SSR safe). */
export function Sparkline({
  seed,
  color = "#34d399",
}: {
  seed: number;
  color?: string;
}) {
  const points = Array.from({ length: 12 }, (_, i) => {
    const wave =
      Math.sin((seed + 1) * 0.37 + i * 0.85) * 0.35 +
      Math.cos((seed + 3) * 0.19 + i * 0.55) * 0.25;
    const y = 18 - (8 + wave * 8 + ((seed + i * 7) % 5));
    const x = 2 + i * (56 / 11);
    return `${x},${Math.max(2, Math.min(22, y))}`;
  }).join(" ");

  return (
    <svg
      viewBox="0 0 60 24"
      className="mt-2 h-6 w-full opacity-80"
      aria-hidden
    >
      <polyline
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
    </svg>
  );
}
