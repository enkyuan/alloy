"use client";

import { useLayoutEffect, useState } from "react";
import { RiAddLine } from "@remixicon/react";

// Measures the features grid at runtime and places + marks exactly on interior border crossings.
// The first row is taller than rows 2-3 (it has logos), so static %-based positioning is wrong.
export function FeaturesGridMarks() {
  const [points, setPoints] = useState<Array<{ x: number; y: number }>>([]);

  useLayoutEffect(() => {
    function measure() {
      // The grid is the relative-positioned ancestor; cards are its grandchildren (link > div).
      const grid = document.getElementById("features-grid");
      if (!grid) return;
      const gridR = grid.getBoundingClientRect();
      const cards = Array.from(grid.querySelectorAll<HTMLElement>(":scope > a > div"));
      if (cards.length < 9) return;
      // Interior row boundaries: bottom of card[2] (= top of card[3]) and bottom of card[5]
      // Interior col boundaries: right of card[0] (= left of card[1]) and right of card[1]
      const r0 = cards[0].getBoundingClientRect();
      const r1 = cards[1].getBoundingClientRect();
      const r2 = cards[2].getBoundingClientRect();
      const r5 = cards[5].getBoundingClientRect();
      const colX1 = r0.right - gridR.left; // right edge of col 0 = left edge of col 1
      const colX2 = r1.right - gridR.left; // right edge of col 1 = left edge of col 2
      const rowY1 = r2.bottom - gridR.top; // bottom of row 0 = top of row 1
      const rowY2 = r5.bottom - gridR.top; // bottom of row 1 = top of row 2
      setPoints([
        { x: colX1, y: rowY1 },
        { x: colX2, y: rowY1 },
        { x: colX1, y: rowY2 },
        { x: colX2, y: rowY2 },
      ]);
    }
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  if (points.length === 0) return null;
  return (
    <>
      {points.map((p, i) => (
        // react-doctor-disable-next-line no-array-index-as-key, react-doctor/no-array-index-as-key
        <RiAddLine
          key={i}
          aria-hidden="true"
          className="hidden md:block absolute pointer-events-none select-none z-10 size-2.5 text-foreground/35 dark:text-foreground/25"
          style={{ left: p.x, top: p.y, transform: "translate(-50%, -50%)" }}
        />
      ))}
    </>
  );
}
