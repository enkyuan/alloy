import type { Metadata } from "next";
import { RootProvider } from "fumadocs-ui/provider/next";
import "./global.css";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { appName } from "@/lib/shared";

export const metadata: Metadata = {
  metadataBase: new URL("http://localhost:3000"),
  title: {
    template: `%s | ${appName}`,
    default: appName,
  },
  description:
    "Embeddable SDK for building agents: event-sourced runtime, tool registry, pluggable LLM providers, and STT/TTS modalities.",
};

export default function Layout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${GeistMono.variable}`}
      suppressHydrationWarning
    >
      <body className="flex flex-col min-h-screen font-sans">
        <RootProvider>{children}</RootProvider>
      </body>
    </html>
  );
}
