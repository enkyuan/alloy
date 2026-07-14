import type { BaseLayoutProps } from "fumadocs-ui/layouts/shared";
import { appName, gitConfig } from "@lib/shared";
import { KajiMark } from "@components/icons";

export function baseOptions(): BaseLayoutProps {
  return {
    nav: {
      title: (
        <>
          <KajiMark />
          <span>{appName}</span>
        </>
      ),
    },
    links: [
      {
        text: "Docs",
        url: "/docs",
        active: "nested-url",
      },
    ],
    githubUrl: `https://github.com/${gitConfig.user}/${gitConfig.repo}`,
  };
}
