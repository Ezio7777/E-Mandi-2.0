import { cn } from "@/utils/cn";

interface LogoMarkProps {
  className?: string;
  title?: string;
}

/**
 * E-Mandi mark: a leaf whose midrib splits into three market nodes.
 * Uses currentColor for the leaf and --primary for nodes, so it themes automatically.
 */
export function LogoMark({ className, title = "E-Mandi" }: LogoMarkProps) {
  return (
    <svg
      viewBox="0 0 48 48"
      role="img"
      aria-label={title}
      className={cn("h-8 w-8 text-primary", className)}
      fill="none"
    >
      <title>{title}</title>
      <rect x="1" y="1" width="46" height="46" rx="13" fill="currentColor" opacity="0.12" />
      <path
        d="M24 41C13.5 38 9 29.5 10.5 17.5 11 13.5 12.5 10.5 14 9c8 .5 17 3.5 21 11 3.5 6.5 1.5 15-4 19.5-2 1.6-4.4 2.4-7 1.5Z"
        fill="currentColor"
      />
      <g stroke="hsl(var(--primary-foreground))" strokeWidth="2" strokeLinecap="round">
        <path d="M24 40V26" />
        <path d="M24 26 17 19" />
        <path d="M24 26 31 19" />
        <path d="M24 30 19.5 27" opacity="0.7" />
      </g>
      <g fill="hsl(var(--primary-foreground))">
        <circle cx="24" cy="25.5" r="2.4" />
        <circle cx="16.5" cy="18.5" r="2" />
        <circle cx="31.5" cy="18.5" r="2" />
      </g>
    </svg>
  );
}
