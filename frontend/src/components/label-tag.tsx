import { CircleHelp, Quote, Sparkles } from "lucide-react";

import type { Label } from "@/lib/api";
import { LABELS } from "@/lib/vocab";
import { cn } from "@/lib/utils";

const ICONS = { sourced: Quote, ai_suggestion: Sparkles, uncertain: CircleHelp } as const;

export function LabelTag({ label, className }: { label: Label; className?: string }) {
  const meta = LABELS[label];
  const Icon = ICONS[label];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[0.8125rem] font-medium",
        meta.text,
        meta.bg,
        meta.border,
        className,
      )}
      title={meta.meaning}
    >
      <Icon aria-hidden className="size-3.5" strokeWidth={2.25} />
      {meta.name}
    </span>
  );
}
