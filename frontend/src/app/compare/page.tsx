import { CompareExplorer } from "@/components/explorer/compare-explorer";


type ComparePageProps = {
  searchParams: Promise<{ player?: string | string[] }>;
};


export default async function ComparePage({ searchParams }: ComparePageProps) {
  const resolved = await searchParams;
  const rawPlayers = resolved.player;
  const players = Array.isArray(rawPlayers) ? rawPlayers : rawPlayers ? [rawPlayers] : [];
  return <CompareExplorer players={players.map((player) => decodeURIComponent(player))} />;
}
