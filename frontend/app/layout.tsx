import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RouteWright",
  description: "Multi-stop transit itinerary planner",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-bg-base text-text-primary antialiased">{children}</body>
    </html>
  );
}
