import type { Metadata } from "next";
import { HeroReadMe } from "@components/landing/hero/readme";
import { HeroTitle } from "@components/landing/hero/title";
import { LineFieldBackground } from "@components/landing/hero/field-bg";
import { SignatureMark } from "@components/landing/signature-mark";
import { getCommunityStats } from "@lib/community-stats";

export const metadata: Metadata = {
  title: "agentkit — open-source agentic platform",
  description:
    "The open-source SDK for building agentic applications. Tool registry, LLM providers, event bus, and more.",
};

export default async function HomePage() {
  const communityStats = await getCommunityStats();

  return (
    <div id="hero" className="relative pt-[45px] lg:pt-0">
      <div className="relative text-foreground" data-v="1">
        <div className="flex flex-col lg:flex-row">
          {/* Left side — Hero title */}
          <div className="relative w-full lg:w-[40%] lg:h-dvh border-b lg:border-b-0 lg:border-r border-foreground/[0.06] px-5 sm:px-6 lg:px-7 lg:sticky lg:top-0 z-10 bg-background lg:overflow-clip">
            <LineFieldBackground />
            <HeroTitle />
            <div className="hidden lg:block absolute left-5 right-5 lg:left-7 lg:right-3 bottom-4 z-[3]">
              <SignatureMark />
            </div>
          </div>

          {/* Right side — README */}
          <div className="relative z-0 w-full lg:w-[60%] overflow-x-hidden">
            <div className="flex items-start lg:items-center justify-center">
              <HeroReadMe
                stats={{
                  npmDownloads: communityStats.npmDownloads,
                  npmWeeklyHistory: communityStats.npmWeeklyHistory,
                  githubStars: communityStats.githubStars,
                  contributors: communityStats.contributors,
                }}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
