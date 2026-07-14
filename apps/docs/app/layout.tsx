import { GeistMono } from "geist/font/mono";
import { GeistPixelSquare } from "geist/font/pixel";
import { GeistSans } from "geist/font/sans";
import "./global.css";
import type { Metadata } from "next";
import { RootProvider } from "fumadocs-ui/provider/next";
import { Nav } from "@components/landing/nav";
import { Providers } from "@components/providers";
import { appName } from "@lib/shared";

export const metadata: Metadata = {
  metadataBase: new URL("http://localhost:3000"),
  title: { template: `%s | ${appName}`, default: appName },
  description:
    "Embeddable SDK for building agents: event-sourced runtime, tool registry, pluggable LLM providers, and STT/TTS modalities.",
};

export default function Layout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      data-scroll-behavior="smooth"
      className={`${GeistSans.variable} ${GeistMono.variable} ${GeistPixelSquare.variable}`}
    >
      <body className="font-sans antialiased">
        <RootProvider>
          <Providers withAgentation={process.env.NODE_ENV !== "production"}>
            <div className="relative min-h-dvh">
              <Nav />
              {children}
            </div>
          </Providers>
        </RootProvider>
      </body>
    </html>
  );
}
