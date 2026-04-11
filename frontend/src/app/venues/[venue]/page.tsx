import { VenueExplorer } from "@/components/explorer/venue-explorer";


type VenuePageProps = {
  params: Promise<{ venue: string }>;
};


export default async function VenuePage({ params }: VenuePageProps) {
  const resolved = await params;
  return <VenueExplorer venueName={decodeURIComponent(resolved.venue)} />;
}
