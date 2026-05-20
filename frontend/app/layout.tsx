import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RouteWright",
  description: "Multi-stop transit itinerary planner",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="flex min-h-screen flex-col bg-bg-base text-text-primary antialiased lg:h-screen lg:overflow-hidden">{children}</body>
    </html>
  );
}
