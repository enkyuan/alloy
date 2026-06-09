import { cn } from "@/lib/utils";

export const AgentkitLogoMark = ({ className }: { className?: string }) => {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" className={className || "size-5"}>
      <path d="M31 3V17L17 3H31Z" fill="#FF6E3C" />
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M45 31V17H31H17V31L3 17L17 3H3V17V31H17V45H31H45V31ZM45 31L31 45L17 31H31V17L45 31Z"
        fill="#FF6E3C"
      />
    </svg>
  );
};

export const AgentkitWordmark = ({ className }: { className?: string }) => {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" className="size-6 shrink-0">
        <path d="M31 3V17L17 3H31Z" fill="#FF6E3C" />
        <path
          fillRule="evenodd"
          clipRule="evenodd"
          d="M45 31V17H31H17V31L3 17L17 3H3V17V31H17V45H31H45V31ZM45 31L31 45L17 31H31V17L45 31Z"
          fill="#FF6E3C"
        />
      </svg>
      <span className="text-lg font-semibold tracking-tight text-foreground">agentkit</span>
    </span>
  );
};
