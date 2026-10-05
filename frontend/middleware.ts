import { NextRequest, NextResponse } from "next/server";
import { backendOrigin, contentSecurityPolicy } from "./lib/security";

export function middleware(request: NextRequest) {
  const development = process.env.NODE_ENV !== "production";
  const origin = backendOrigin(process.env.NEXT_PUBLIC_API_URL ?? "", !development);
  const nonce = btoa(crypto.randomUUID());
  const csp = contentSecurityPolicy(nonce, origin, development);
  const headers = new Headers(request.headers);
  headers.set("x-nonce", nonce);
  headers.set("Content-Security-Policy", csp);
  const response = NextResponse.next({ request: { headers } });
  response.headers.set("Content-Security-Policy", csp);
  response.headers.set("Cache-Control", "private, no-store");
  if (process.env.SECURITY_HSTS_ENABLED === "true" && !development) {
    response.headers.set("Strict-Transport-Security", "max-age=31536000");
  }
  return response;
}
export const config = { matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"] };
