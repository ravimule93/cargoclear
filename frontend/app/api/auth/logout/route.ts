import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const returnTo = request.nextUrl.searchParams.get("returnTo") || "/";
  const targetUrl = new URL(returnTo, request.nextUrl.origin);
  const response = NextResponse.redirect(targetUrl);

  response.cookies.set("cargoclear_session_token", "", {
    path: "/",
    maxAge: 0,
    sameSite: "lax",
  });

  return response;
}
