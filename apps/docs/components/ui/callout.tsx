import { cva } from "class-variance-authority";
import {
  RiCheckboxCircleLine,
  RiCloseCircleLine,
  RiInformationLine,
  RiAlertLine,
} from "@remixicon/react";
import type * as React from "react";
import type { ReactNode } from "react";
import { cn } from "@lib/utils";

type CalloutProps = Omit<React.HTMLAttributes<HTMLDivElement>, "title" | "type" | "icon"> & {
  ref?: React.Ref<HTMLDivElement>;
  title?: ReactNode;
  /**
   * @defaultValue info
   */
  type?: "info" | "warn" | "error" | "success" | "warning";

  /**
   * Force an icon
   */
  icon?: ReactNode;
};

const calloutVariants = cva(
  "my-4 flex gap-2 rounded-lg border border-s-2 bg-fd-card p-3 text-sm text-fd-card-foreground shadow-md border-dashed rounded-none",
  {
    variants: {
      type: {
        info: "border-s-blue-500/50",
        warn: "border-s-orange-500/50",
        error: "border-s-red-500/50",
        success: "border-s-green-500/50",
      },
    },
  },
);

export function Callout({
  className,
  children,
  title,
  type = "info",
  icon,
  ref,
  ...props
}: CalloutProps) {
  if (type === "warning") type = "warn";

  return (
    <div
      ref={ref}
      className={cn(
        calloutVariants({
          type: type,
        }),
        className,
      )}
      {...props}
    >
      {icon ??
        {
          info: <RiInformationLine size={20} className="fill-blue-500 text-fd-card" />,
          warn: <RiAlertLine size={20} className="fill-orange-500 text-fd-card" />,
          error: <RiCloseCircleLine size={20} className="fill-red-500 text-fd-card" />,
          success: <RiCheckboxCircleLine size={20} className="fill-green-500 text-fd-card" />,
        }[type]}
      <div className="min-w-0 flex flex-col gap-2 flex-1">
        {title ? <p className="font-medium !my-0">{title}</p> : null}
        <div className="text-fd-muted-foreground prose-no-margin empty:hidden">{children}</div>
      </div>
    </div>
  );
}
