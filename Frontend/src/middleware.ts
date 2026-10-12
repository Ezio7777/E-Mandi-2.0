import { NextResponse, type NextRequest } from "next/server";

const PROTECTED = ["/farmer", "/buyer", "/admin"];
/**
 * UX-only gate: redirects when no session hint cookie exists. Real authorization is
 * enforced by the backend on every API call; the client RoleGuard handles role mismatches.
 */
export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (PROTECTED.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
    if (!req.cookies.has("emandi_session")) {
      const url = req.nextUrl.clone();
      url.pathname = "/login";
      url.searchParams.set("next", pathname);
      return NextResponse.redirect(url);
    }
  }
  return NextResponse.next();
}

export const config = { matcher: ["/farmer/:path*", "/buyer/:path*", "/admin/:path*"] };
