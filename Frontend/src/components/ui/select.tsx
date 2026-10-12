import * as React from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/utils/cn";

interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> { containerClassName?: string }

/** Native select (best on mobile) with our own chevron, so the arrow has proper breathing room. */
const Select = React.forwardRef<HTMLSelectElement, SelectProps>(({ className, containerClassName, children, ...props }, ref) => (
  <div className={cn("relative", containerClassName)}>
    <select
      ref={ref}
      className={cn(
        "min-h-touch w-full appearance-none rounded-md border border-input bg-background py-2 pl-3 pr-10 text-base transition-colors disabled:cursor-not-allowed disabled:opacity-50 sm:text-sm",
        className,
      )}
      {...props}
    >
      {children}
    </select>
    <ChevronDown className="pointer-events-none absolute right-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
  </div>
));
Select.displayName = "Select";
export { Select };
