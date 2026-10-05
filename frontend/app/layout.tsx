import type { Metadata } from "next";
import "./globals.css";
import { headers } from "next/headers";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "RouteWright",
  description: "Multi-stop transit itinerary planner",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html lang="en">
      <head><style nonce={nonce} /></head>
      <body className="flex min-h-screen flex-col text-text-primary antialiased lg:h-screen lg:overflow-hidden">{children}</body>
    </html>
  );
}
