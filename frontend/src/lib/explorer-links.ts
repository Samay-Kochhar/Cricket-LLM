import type { QueryResponse } from "@/lib/api-types";


export type ExplorerLink = {
  href: string;
  label: string;
};


export function buildPlayerHref(playerName: string) {
  return `/players/${encodeURIComponent(playerName)}`;
}


export function buildVenueHref(venueName: string) {
  return `/venues/${encodeURIComponent(venueName)}`;
}


export function buildCompareHref(players: string[]) {
  const params = new URLSearchParams();
  for (const player of players.slice(0, 2)) {
    params.append("player", player);
  }
  return `/compare?${params.toString()}`;
}


export function deriveExplorerLinks(result: QueryResponse): ExplorerLink[] {
  const links: ExplorerLink[] = [];
  const entities = Array.from(new Set(result.interpretation.entities));
  const venueName = typeof result.interpretation.filters.venue_name === "string"
    ? result.interpretation.filters.venue_name
    : null;

  if (entities.length >= 2) {
    links.push({
      href: buildCompareHref(entities),
      label: `Compare ${entities.slice(0, 2).join(" vs ")}`,
    });
  }

  for (const entity of entities) {
    links.push({
      href: buildPlayerHref(entity),
      label: `Open ${entity}`,
    });
  }

  if (venueName) {
    links.push({
      href: buildVenueHref(venueName),
      label: `Open ${venueName}`,
    });
  }

  return links;
}


export function derivePrimaryExplorerHref(result: QueryResponse): string | null {
  const links = deriveExplorerLinks(result);
  return links[0]?.href ?? null;
}
