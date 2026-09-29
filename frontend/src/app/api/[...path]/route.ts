import { NextRequest, NextResponse } from "next/server";

import { BACKEND_IDENTITY_HEADER, internalBackendUrl } from "@/lib/backend-routing";


const BACKEND_INTERNAL_URL = internalBackendUrl();

export const dynamic = "force-dynamic";


async function proxy(request: NextRequest, pathSegments: string[]) {
  const path = pathSegments.join("/");
  const target = new URL(`${BACKEND_INTERNAL_URL}/api/${path}`);
  target.search = request.nextUrl.search;

  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) {
    headers.set("content-type", contentType);
  }

  const init: RequestInit = {
    method: request.method,
    headers,
    cache: "no-store",
  };

  if (!["GET", "HEAD"].includes(request.method)) {
    init.body = await request.text();
  }

  let response: Response;
  try {
    response = await fetch(target, init);
  } catch {
    return NextResponse.json(
      {
        error: "CricAtlas backend is unavailable",
        detail: `No response from BACKEND_INTERNAL_URL (${BACKEND_INTERNAL_URL}). Start the CricAtlas API there or set BACKEND_INTERNAL_URL to its address.`,
        target: target.toString(),
      },
      { status: 502 },
    );
  }
  if (!response.headers.has(BACKEND_IDENTITY_HEADER)) {
    // Another service at the internal URL must never answer CricAtlas requests.
    return NextResponse.json(
      {
        error: "CricAtlas backend is unavailable",
        detail: `The service at BACKEND_INTERNAL_URL (${BACKEND_INTERNAL_URL}) did not identify as the CricAtlas API. Set BACKEND_INTERNAL_URL to the CricAtlas backend address.`,
        target: target.toString(),
      },
      { status: 502 },
    );
  }
  const body = await response.text();
  return new NextResponse(body, {
    status: response.status,
    headers: {
      "content-type": response.headers.get("content-type") ?? "application/json",
    },
  });
}


type RouteContext = {
  params: Promise<{ path: string[] }>;
};


export async function GET(request: NextRequest, context: RouteContext) {
  const params = await context.params;
  return proxy(request, params.path);
}


export async function POST(request: NextRequest, context: RouteContext) {
  const params = await context.params;
  return proxy(request, params.path);
}
