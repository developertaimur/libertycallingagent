import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { toneClass, type BadgeTone } from "@/lib/status";

export function Badge({
  tone = "slate",
  className,
  children,
}: {
  tone?: BadgeTone;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize tracking-normal ring-1 ring-inset",
        toneClass[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
