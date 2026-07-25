const MIN_ACTIVATION_LINE = 96;
const MAX_ACTIVATION_LINE = 240;
const ACTIVATION_RATIO = 0.25;
const PAGE_END_TOLERANCE = 2;

export function tocActivationLine(viewportHeight: number, scrollY: number, maxScrollY: number) {
  const safeViewportHeight = Math.max(0, viewportHeight);
  const readingLine = Math.min(
    safeViewportHeight,
    MAX_ACTIVATION_LINE,
    Math.max(MIN_ACTIVATION_LINE, safeViewportHeight * ACTIVATION_RATIO),
  );
  const tailRange = safeViewportHeight - readingLine;
  const tailStart = Math.max(0, maxScrollY - tailRange);
  if (scrollY <= tailStart || tailRange <= 0) return readingLine;

  const tailProgress = Math.min(1, (scrollY - tailStart) / Math.max(1, maxScrollY - tailStart));
  return readingLine + tailRange * tailProgress;
}

export function activeTocIndex(
  headingTops: number[],
  viewportHeight: number,
  scrollY: number,
  maxScrollY: number,
) {
  if (headingTops.length === 0) return -1;
  if (scrollY <= PAGE_END_TOLERANCE || maxScrollY <= 0) return 0;

  const activationLine = tocActivationLine(viewportHeight, scrollY, maxScrollY);
  let activeIndex = 0;

  for (let index = 0; index < headingTops.length; index += 1) {
    if (headingTops[index] > activationLine) break;
    activeIndex = index;
  }

  return activeIndex;
}
