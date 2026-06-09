import { source } from "@lib/source";
import { DocsLayout } from "fumadocs-ui/layouts/docs";
import { baseOptions } from "@app/layout.config";
import { DocsSidebar } from "@components/docs/sidebar/root";

export default function Layout({ children }: LayoutProps<"/docs">) {
  return (
    <>
      <DocsSidebar />
      <DocsLayout
        tree={source.getPageTree()}
        {...baseOptions()}
        nav={{ enabled: false }}
        searchToggle={{ enabled: false }}
        themeSwitch={{ enabled: false }}
        sidebar={{ enabled: false }}
        containerProps={{ className: "docs-layout" }}
      >
        {children}
      </DocsLayout>
    </>
  );
}
