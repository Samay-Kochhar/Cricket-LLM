import { NextRequest, NextResponse } from "next/server";


const BACKEND_INTERNAL_URL =
  process.env.BACKEND_INTERNAL_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

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

  try {
    const response = await fetch(target, init);
    const body = await response.text();
    return new NextResponse(body, {
      status: response.status,
      headers: {
        "content-type": response.headers.get("content-type") ?? "application/json",
      },
    });
  } catch {
    return NextResponse.json(
      { error: "Backend is unavailable", target: target.toString() },
      { status: 502 },
    );
  }
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
