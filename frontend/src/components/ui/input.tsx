import type { InputHTMLAttributes, TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export function Input({
  className,
  ...rest
}: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm",
        "placeholder:text-slate-400 focus:border-axon-navy focus:outline-none",
        "focus:ring-1 focus:ring-axon-navy/40",
        className,
      )}
      {...rest}
    />
  );
}

export function Textarea({
  className,
  ...rest
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        "rounded-md border border-slate-200 bg-white px-3 py-2 font-mono text-xs",
        "leading-5 focus:border-axon-navy focus:outline-none focus:ring-1",
        "focus:ring-axon-navy/40",
        className,
      )}
      {...rest}
    />
  );
}
