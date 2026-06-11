"use client";

import { useRef, useState } from "react";

export function useDropdown() {
  const [open, setOpen] = useState(false);
  const timeout = useRef<NodeJS.Timeout>(undefined);

  const openDropdown = () => {
    clearTimeout(timeout.current);
    setOpen(true);
  };

  const closeDropdown = () => {
    timeout.current = setTimeout(() => setOpen(false), 150);
  };

  return { open, openDropdown, closeDropdown };
}
