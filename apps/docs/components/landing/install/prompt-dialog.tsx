"use client";

import { AnimatePresence, LazyMotion, domAnimation, m } from "motion/react";
import { CopyIcon, CheckIcon, CloseIcon } from "@components/docs/icons/ui";

type Props = {
  open: boolean;
  copied: boolean;
  promptText: string;
  onClose: () => void;
  onCopy: (text: string) => void;
};

export function PromptDialog({ open, copied, promptText, onClose, onCopy }: Props) {
  return (
    <LazyMotion features={domAnimation}>
      <AnimatePresence>
        {open && (
          <m.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 lg:left-[40%] z-50 flex items-center justify-center"
            onClick={onClose}
          >
            {/* Backdrop */}
            <div className="absolute inset-0 bg-black/50 dark:bg-black/70 backdrop-blur-sm" />

            {/* Dialog */}
            <m.div
              initial={{ opacity: 0, y: 8, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 8, scale: 0.98 }}
              transition={{ duration: 0.2, ease: "easeOut" }}
              onClick={(e) => e.stopPropagation()}
              className="relative w-[calc(100%-2rem)] max-w-lg mx-4 bg-neutral-50 dark:bg-[#0a0a0a] border border-neutral-200 dark:border-white/[0.06] rounded-sm shadow-2xl"
            >
              {/* Close */}
              <button
                type="button"
                onClick={onClose}
                aria-label="Close"
                className="absolute top-3 right-3 text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300 transition-colors z-10"
              >
                <CloseIcon className="h-4 w-4" />
              </button>

              {/* Content */}
              <div className="px-5 py-5 max-h-[60vh] overflow-y-auto">
                <p className="text-[12px] font-mono text-neutral-600 dark:text-neutral-400 leading-[1.9] whitespace-pre-line">
                  {promptText}
                </p>
              </div>

              {/* Footer */}
              <div className="flex justify-end px-5 py-3 border-t border-neutral-200 dark:border-white/[0.06]">
                <button
                  type="button"
                  onClick={() => onCopy(promptText)}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] rounded-sm border border-neutral-200 dark:border-white/[0.08] text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200 hover:bg-neutral-100 dark:hover:bg-white/[0.04] transition-colors"
                >
                  {copied ? (
                    <>
                      <CheckIcon className="h-3.5 w-3.5" />
                      Copied
                    </>
                  ) : (
                    <>
                      <CopyIcon className="h-3.5 w-3.5" />
                      Copy prompt
                    </>
                  )}
                </button>
              </div>
            </m.div>
          </m.div>
        )}
      </AnimatePresence>
    </LazyMotion>
  );
}
