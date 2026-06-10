import type { BaseLayoutProps } from "fumadocs-ui/layouts/shared";
import { appName, gitConfig } from "@lib/shared";
import { AgentkitMark } from "@components/icons";

export function baseOptions(): BaseLayoutProps {
  return {
    nav: {
      title: (
        <>
          <AgentkitMark />
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
