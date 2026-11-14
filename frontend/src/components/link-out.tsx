import { ExternalLink } from "lucide-react";
import Link from "next/link";

const BASE = "text-ink underline underline-offset-4";

/** A link that opens in a new tab when it leaves Ritam, and says so to screen readers. */
export function LinkOut({
  href,
  children,
  className = "hover:no-underline",
}: {
  href: string;
  children: React.ReactNode;
  className?: string;
}) {
  if (href.startsWith("/"))
    return (
      <Link href={href} className={`font-medium ${BASE} ${className}`}>
        {children}
      </Link>
    );
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={`inline-flex items-center gap-1 ${BASE} ${className}`}>
      {children}
      <ExternalLink aria-hidden className="size-3.5" />
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  );
}
