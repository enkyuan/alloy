import { GeistPixelSquare } from "geist/font/pixel";
import { Geist, Geist_Mono } from "next/font/google";
import "./global.css";
import type { Metadata } from "next";
import { RootProvider } from "fumadocs-ui/provider/next";
import { StaggeredNavFiles } from "@/components/landing/staggered-nav-files";
import { Providers } from "@/components/providers";
import { appName } from "@/lib/shared";

const fontSans = Geist({ subsets: ["latin"], variable: "--font-sans" });
const fontMono = Geist_Mono({ subsets: ["latin"], variable: "--font-mono" });

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
      className={`${fontSans.variable} ${fontMono.variable} ${GeistPixelSquare.variable}`}
    >
      <body className="font-sans antialiased">
        <RootProvider>
          <Providers>
            <div className="relative min-h-dvh">
              <StaggeredNavFiles />
              {children}
            </div>
          </Providers>
        </RootProvider>
      </body>
    </html>
  );
}
