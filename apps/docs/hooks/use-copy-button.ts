"use client";
import type { MouseEventHandler } from "react";
import { useCallback, useEffect, useRef, useState } from "react";

export function useCopyButton(
  onCopy: () => void | Promise<void>,
): [checked: boolean, onClick: MouseEventHandler] {
  const [checked, setChecked] = useState(false);
  const timeoutRef = useRef<number | null>(null);
  const onCopyRef = useRef(onCopy);
  onCopyRef.current = onCopy;

  const onClick: MouseEventHandler = useCallback(() => {
    if (timeoutRef.current) window.clearTimeout(timeoutRef.current);
    const res = Promise.resolve(onCopyRef.current());

    void res.then(() => {
      setChecked(true);
      timeoutRef.current = window.setTimeout(() => {
        setChecked(false);
      }, 1500);
    });
  }, []);

  // Avoid updates after being unmounted
  // react-doctor-disable-next-line exhaustive-deps, react-doctor/exhaustive-deps
  useEffect(() => {
    return () => {
      if (timeoutRef.current) window.clearTimeout(timeoutRef.current);
    };
  }, []);

  return [checked, onClick];
}
