import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const styles: Record<Variant, string> = {
  primary:
    "bg-axon-navy text-white hover:bg-axon-navy/90 focus-visible:outline-axon-navy",
  secondary:
    "border border-slate-200 bg-white text-slate-800 hover:bg-slate-50",
  ghost: "text-slate-600 hover:bg-slate-100",
  danger: "bg-rose-600 text-white hover:bg-rose-700",
};

export function Button({
  variant = "primary",
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  children: ReactNode;
}) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-md px-3 py-1.5 " +
          "text-sm font-medium transition-colors disabled:cursor-not-allowed " +
          "disabled:opacity-50 focus-visible:outline focus-visible:outline-2 " +
          "focus-visible:outline-offset-2",
        styles[variant],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}
