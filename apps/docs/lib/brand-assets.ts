export const brandAssetPaths = {
  assetsZip: "/logo.svg",
  mark: {
    light: {
      svg: "/logo.svg",
      png: "/logo.svg",
    },
    dark: {
      svg: "/logo.svg",
      png: "/logo.svg",
    },
  },
  wordmark: {
    light: {
      svg: "/logo.svg",
      png: "/logo.svg",
    },
    dark: {
      svg: "/logo.svg",
      png: "/logo.svg",
    },
  },
} as const;

const brandLogoPreviews = [
  {
    label: "Mark · Light",
    src: brandAssetPaths.mark.light.svg,
    bg: "bg-black",
  },
  {
    label: "Mark · Dark",
    src: brandAssetPaths.mark.dark.svg,
    bg: "bg-white",
  },
  {
    label: "Wordmark · Light",
    src: brandAssetPaths.wordmark.light.svg,
    bg: "bg-black",
  },
  {
    label: "Wordmark · Dark",
    src: brandAssetPaths.wordmark.dark.svg,
    bg: "bg-white",
  },
] as const;
