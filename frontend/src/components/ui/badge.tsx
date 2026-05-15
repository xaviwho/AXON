import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

type Variant = "default" | "success" | "warning" | "danger" | "muted";

const styles: Record<Variant, string> = {
  default: "bg-axon-navy/10 text-axon-navy border-axon-navy/20",
  success: "bg-emerald-50 text-emerald-700 border-emerald-200",
  warning: "bg-amber-50 text-amber-700 border-amber-200",
  danger:  "bg-rose-50 text-rose-700 border-rose-200",
  muted:   "bg-slate-100 text-slate-600 border-slate-200",
};

export function Badge({
  variant = "default",
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLSpanElement> & { variant?: Variant; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium",
        styles[variant],
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
}

export function severityBadge(sev: number): Variant {
  if (sev >= 4) return "danger";
  if (sev >= 2) return "warning";
  return "muted";
}

export function effectBadge(effect: string): Variant {
  if (effect === "success") return "success";
  if (effect === "timeout") return "warning";
  return "danger";
}
