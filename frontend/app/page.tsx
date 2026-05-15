// Day 9: renders fixture data to lock the visual hierarchy.
// Replaced by <PlannerPage /> on Day 10.
import Timeline from "@/components/Timeline";
import { FIXTURE_PLAN } from "@/lib/fixture";

export default function Home() {
  return (
    <main className="max-w-lg mx-auto px-4 py-10">
      <h1 className="text-2xl font-bold text-zinc-900 mb-8">RouteWright</h1>
      <Timeline plan={FIXTURE_PLAN} />
    </main>
  );
}
