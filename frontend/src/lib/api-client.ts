const DEFAULT_API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "";


export async function fetchApi<T>(path: string): Promise<T> {
  const response = await fetch(`${DEFAULT_API_BASE_URL}${path}`, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }

  return (await response.json()) as T;
}


export function getApiBaseUrl() {
  return DEFAULT_API_BASE_URL;
}
