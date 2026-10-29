import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/60 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default:
          "bg-cyan-500 text-slate-950 hover:bg-cyan-400 shadow-[0_0_24px_-8px_rgba(34,211,238,0.7)]",
        secondary:
          "bg-slate-800 text-slate-100 hover:bg-slate-700 ring-1 ring-slate-700",
        success:
          "bg-emerald-500 text-slate-950 hover:bg-emerald-400 shadow-[0_0_24px_-8px_rgba(16,185,129,0.75)]",
        danger:
          "bg-rose-500 text-white hover:bg-rose-400 shadow-[0_0_24px_-8px_rgba(244,63,94,0.7)]",
        ghost: "hover:bg-slate-800/80 text-slate-200",
        outline:
          "border border-slate-700 bg-transparent text-slate-100 hover:bg-slate-900",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-8 rounded-md px-3 text-xs",
        lg: "h-12 rounded-xl px-6 text-base",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  ),
);
Button.displayName = "Button";
