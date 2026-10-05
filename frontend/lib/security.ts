/** Shared CSP policy: nonces authorise framework and Maps bootstrap scripts. */
export function backendOrigin(value: string, production: boolean): string {
  if (!value) {
    if (production) throw new Error("NEXT_PUBLIC_API_URL is required in production");
    return "";
  }
  const url = new URL(value);
  if (url.username || url.password || url.search || url.hash || (url.pathname !== "/" && url.pathname !== "")) {
    throw new Error("NEXT_PUBLIC_API_URL must be an origin without credentials or a path");
  }
  if (production && (url.protocol !== "https:" || ["localhost", "127.0.0.1"].includes(url.hostname))) {
    throw new Error("Production API origin must use HTTPS");
  }
  if (!["https:", "http:"].includes(url.protocol)) throw new Error("Invalid API protocol");
  return url.origin;
}

export function contentSecurityPolicy(nonce: string, apiOrigin: string, development: boolean): string {
  const google = "https://*.googleapis.com https://*.gstatic.com https://*.google.com https://*.googleusercontent.com https://*.ggpht.com";
  return [
    "default-src 'none'",
    `script-src 'self' 'nonce-${nonce}' ${google}${development ? " 'unsafe-eval'" : ""}`,
    `style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://maps.googleapis.com`,
    "font-src 'self' https://fonts.gstatic.com",
    `img-src 'self' data: blob: ${google}`,
    `connect-src 'self' ${google} ${apiOrigin}${development ? " ws://localhost:*" : ""}`,
    "worker-src 'self' blob:",
    "frame-src https://www.google.com",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
  ].join("; ");
}
