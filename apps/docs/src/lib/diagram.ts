export const DIAGRAM_TOKEN_STEP_MS = 42;

interface DiagramToken {
  text: string;
  animated: boolean;
  index: number;
}

const frameGlyphs = new Set([
  "\u2500",
  "\u2502",
  "\u250c",
  "\u2510",
  "\u2514",
  "\u2518",
  "\u251c",
  "\u2524",
  "\u252c",
  "\u2534",
  "\u253c",
]);

const escapeHtml = (value: string) =>
  value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

export const diagramLayer = (text: string, frame: boolean) =>
  Array.from(text, (character) => (frameGlyphs.has(character) === frame ? character : " ")).join(
    "",
  );

export const tokenizeDiagramText = (text: string): DiagramToken[] => {
  const chunks = text.match(/\s+|[\p{L}\p{N}_]+|[^\s]/gu) ?? [];
  let tokenIndex = 0;

  return chunks.map((chunk) => {
    const animated = !/^\s+$/u.test(chunk);
    const token = { text: chunk, animated, index: tokenIndex };
    if (animated) tokenIndex += 1;
    return token;
  });
};

export const countDiagramTokens = (text: string) =>
  tokenizeDiagramText(text).filter(({ animated }) => animated).length;

export const diagramTokenMarkup = (text: string) =>
  tokenizeDiagramText(text)
    .map(({ text: token, animated, index }) =>
      animated
        ? `<span class="diagram-token" style="--diagram-token-index: ${index}">${escapeHtml(token)}</span>`
        : escapeHtml(token),
    )
    .join("");

export const diagramConnectorMarkup = (text: string) =>
  Array.from(text, (character) =>
    character === "\u25bc" ? '<span class="diagram-arrow">\u25bc</span>' : escapeHtml(character),
  ).join("");

export const setupDiagramMotion = (scope: Document = document) => {
  const root = scope.documentElement;
  const targets = [
    ...scope.querySelectorAll<HTMLElement>("[data-kaji-once]:not([data-kaji-ready])"),
  ];
  const timers = new Set<number>();
  const activeTargets = new Set<HTMLElement>();
  let observer: IntersectionObserver | undefined;

  const showStatic = () => {
    targets.forEach((target) => {
      target.dataset.kajiReady = "";
    });
  };

  if (!root.hasAttribute("data-kaji-motion")) {
    showStatic();
    return () => {};
  }

  let storage: Storage;
  try {
    storage = window.sessionStorage;
  } catch {
    showStatic();
    return () => {};
  }

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const reveal = (target: HTMLElement) => {
    const id = target.getAttribute("data-kaji-once");
    if (!id) {
      target.dataset.kajiReady = "";
      return;
    }

    const key = `kaji:motion:${id}`;
    try {
      if (storage.getItem(key) || reducedMotion) {
        storage.setItem(key, "true");
        target.dataset.kajiReady = "";
        return;
      }
    } catch {
      target.dataset.kajiReady = "";
      return;
    }

    target.dataset.kajiAnimate = "";
    target.dataset.kajiReady = "";
    activeTargets.add(target);
    const durationAttribute = root.hasAttribute("data-kaji-first-visit")
      ? target.getAttribute("data-kaji-first-duration")
      : null;
    const requestedDuration = Number.parseInt(
      durationAttribute ?? target.getAttribute("data-kaji-duration") ?? "",
      10,
    );
    const duration = Number.isFinite(requestedDuration)
      ? Math.min(Math.max(requestedDuration, 0), 10000)
      : 5000;
    const timer = window.setTimeout(() => {
      try {
        storage.setItem(key, "true");
      } catch {
        // Storage can become unavailable while the page is open; visual cleanup still completes.
      }
      delete target.dataset.kajiAnimate;
      activeTargets.delete(target);
      timers.delete(timer);
    }, duration);
    timers.add(timer);
  };

  const pending = targets.filter((target) => {
    const id = target.getAttribute("data-kaji-once");
    if (!id) {
      target.dataset.kajiReady = "";
      return false;
    }

    try {
      if (storage.getItem(`kaji:motion:${id}`) || reducedMotion) {
        storage.setItem(`kaji:motion:${id}`, "true");
        target.dataset.kajiReady = "";
        return false;
      }
    } catch {
      target.dataset.kajiReady = "";
      return false;
    }
    return true;
  });

  if ("IntersectionObserver" in window) {
    observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting || !(entry.target instanceof HTMLElement)) continue;
          observer?.unobserve(entry.target);
          reveal(entry.target);
        }
      },
      { rootMargin: "0px 0px -10% 0px", threshold: 0.2 },
    );
    pending.forEach((target) => observer?.observe(target));
  } else {
    pending.forEach(reveal);
  }

  return () => {
    observer?.disconnect();
    timers.forEach((timer) => window.clearTimeout(timer));
    timers.clear();
    activeTargets.forEach((target) => {
      target.removeAttribute("data-kaji-animate");
      target.removeAttribute("data-kaji-ready");
    });
    activeTargets.clear();
  };
};
