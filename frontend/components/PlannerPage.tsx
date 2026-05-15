"use client";

import { useState } from "react";
import type { Plan, PlanRequest } from "@/lib/types";
import { postPlan } from "@/lib/api";
import PlanForm from "./PlanForm";
import Timeline from "./Timeline";

const DEFAULT_FORM: PlanRequest = {
  city: "",
  stops: [{ query: "" }, { query: "" }],
  start_time: "",
  mode: "transit",
};

export default function PlannerPage() {
  const [form, setForm] = useState<PlanRequest>(DEFAULT_FORM);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  async function handleSubmit(req: PlanRequest) {
    setStatus("loading");
    setErrorMsg(null);
    try {
      const result = await postPlan(req);
      setPlan(result);
      setStatus("idle");
    } catch (err) {
      setStatus("error");
      setErrorMsg(err instanceof Error ? err.message : "Something went wrong.");
    }
  }

  return (
    <main className="mx-auto max-w-lg px-4 py-10">
      <h1 className="mb-8 text-2xl font-bold text-zinc-900">RouteWright</h1>

      {/* Error — show API message verbatim so users can fix failing stops */}
      {status === "error" && errorMsg && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {errorMsg}
        </div>
      )}

      <PlanForm
        form={form}
        onChange={setForm}
        onSubmit={handleSubmit}
        isLoading={status === "loading"}
      />

      {/* Empty state */}
      {status === "idle" && plan === null && (
        <p className="mt-4 text-center text-sm text-zinc-400">
          Enter your stops and tap Generate.
        </p>
      )}

      {plan !== null && (
        <div className="mt-8">
          <Timeline plan={plan} />
        </div>
      )}
    </main>
  );
}
