export interface CommunityStats {
  npmDownloads: number;
  npmWeeklyHistory: number[];
  githubStars: number;
  contributors: number;
  discordMembers: number;
}

export interface ContributorInfo {
  login: string;
  avatar_url: string;
  html_url: string;
}

// kaji has no published npm package or large public repo yet, so the
// landing renders static placeholder figures rather than live API fetches.
// The shape mirrors what the hero readme consumes; swap in live fetches once
// the package is published.
const staticContributors: ContributorInfo[] = [
  {
    login: "enkyuan",
    avatar_url: "https://github.com/enkyuan.png",
    html_url: "https://github.com/enkyuan",
  },
];

export async function getCommunityStats(): Promise<CommunityStats> {
  return {
    npmDownloads: 0,
    npmWeeklyHistory: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    githubStars: 0,
    contributors: staticContributors.length,
    discordMembers: 0,
  };
}
