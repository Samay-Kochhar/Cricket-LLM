import { PlayerExplorer } from "@/components/explorer/player-explorer";


type PlayerPageProps = {
  params: Promise<{ player: string }>;
};


export default async function PlayerPage({ params }: PlayerPageProps) {
  const resolved = await params;
  return <PlayerExplorer playerName={decodeURIComponent(resolved.player)} />;
}
