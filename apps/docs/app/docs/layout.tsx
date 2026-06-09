import { source } from "@/lib/source";
import { DocsLayout } from "fumadocs-ui/layouts/docs";
import { baseOptions } from "@/lib/layout.shared";
import { DocsSidebar } from "@/components/docs/docs-sidebar";

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
