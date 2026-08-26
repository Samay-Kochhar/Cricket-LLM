import { MatchupExplorer } from "@/components/explorer/matchup-explorer";

type MatchupsPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

function first(value: string | string[] | undefined, fallback = "") {
  return Array.isArray(value) ? value[0] ?? fallback : value ?? fallback;
}

export default async function MatchupsPage({ searchParams }: MatchupsPageProps) {
  const params = await searchParams;
  return (
    <MatchupExplorer
      initialBatter={first(params.batter, "Steven Smith")}
      initialBowler={first(params.bowler, "Jasprit Bumrah")}
      initialPhase={first(params.phase, "all")}
      initialVenue={first(params.venue)}
      initialYear={first(params.year)}
    />
  );
}
