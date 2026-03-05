"use client";

import { useRouter } from "next/navigation";
import {
  createSession,
  type ContentType,
  type Audience,
  type CampaignGoal,
  type Tone,
} from "@/lib/api";
import { useState } from "react";

const CONTENT_TYPES: { value: ContentType; label: string; desc: string }[] = [
  { value: "email", label: "HCP Email", desc: "Promotional email for healthcare professionals" },
  { value: "banner", label: "Banner Ad", desc: "728×90 leaderboard display ad" },
  { value: "social", label: "Social Post", desc: "Card-style social media content" },
];

const AUDIENCES: { value: Audience; label: string }[] = [
  { value: "hcp", label: "Healthcare Providers" },
  { value: "patients", label: "Patients" },
  { value: "caregivers", label: "Caregivers" },
  { value: "payers", label: "Payers" },
];

const GOALS: { value: CampaignGoal; label: string }[] = [
  { value: "awareness", label: "Disease Awareness" },
  { value: "education", label: "Clinical Education" },
  { value: "cta", label: "Call-to-Action" },
  { value: "launch", label: "Product Launch" },
];

const TONES: { value: Tone; label: string }[] = [
  { value: "clinical", label: "Clinical" },
  { value: "empathetic", label: "Empathetic" },
  { value: "urgent", label: "Urgent" },
  { value: "informative", label: "Informative" },
];

export default function LandingPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [contentType, setContentType] = useState<ContentType>("email");
  const [audience, setAudience] = useState<Audience>("hcp");
  const [goal, setGoal] = useState<CampaignGoal>("awareness");
  const [tone, setTone] = useState<Tone>("clinical");

  async function handleStart() {
    console.log("[Landing] Starting session — type=%s, audience=%s, goal=%s, tone=%s", contentType, audience, goal, tone);
    setLoading(true);
    try {
      const info = await createSession({
        content_type: contentType,
        audience,
        campaign_goal: goal,
        tone,
      });
      localStorage.setItem("session_id", info.session_id);
      localStorage.setItem("content_type", contentType);
      console.log("[Landing] Session created, navigating to /chat — session_id=%s", info.session_id);
      router.push("/chat");
    } catch (err) {
      console.error("[Landing] Failed to create session:", err);
      alert("Failed to create session. Is the backend running at localhost:8000?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-[80vh] gap-8">
      <div className="text-center space-y-3">
        <p className="text-xs uppercase tracking-widest text-muted font-medium">
          Solistic Health &middot; Content Studio
        </p>
        <h1 className="text-4xl font-bold tracking-tight text-primary">
          FRUZAQLA<sup className="text-lg">&reg;</sup> Content Generator
        </h1>
        <p className="text-muted text-base max-w-lg mx-auto leading-relaxed">
          Create FDA-compliant promotional content for fruquintinib from
          approved claims and clinical literature.
        </p>
      </div>

      <div className="w-full max-w-2xl space-y-6">
        {/* Content format */}
        <div>
          <label className="text-sm font-medium text-foreground block mb-2">Content Format</label>
          <div className="grid grid-cols-3 gap-3">
            {CONTENT_TYPES.map((ct) => (
              <button
                key={ct.value}
                onClick={() => setContentType(ct.value)}
                className={`rounded-lg border-2 p-3.5 text-left transition-all cursor-pointer ${
                  contentType === ct.value
                    ? "border-primary bg-[#f0f4ff]"
                    : "border-border bg-surface hover:border-muted"
                }`}
              >
                <div className="font-semibold text-sm text-foreground">{ct.label}</div>
                <div className="text-xs text-muted mt-0.5">{ct.desc}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Audience + Goal + Tone row */}
        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="text-sm font-medium text-foreground block mb-2">Target Audience</label>
            <div className="space-y-1.5">
              {AUDIENCES.map((a) => (
                <button
                  key={a.value}
                  onClick={() => setAudience(a.value)}
                  className={`w-full rounded-md border px-3 py-2 text-left text-sm transition-all cursor-pointer ${
                    audience === a.value
                      ? "border-primary bg-[#f0f4ff] text-primary font-medium"
                      : "border-border bg-surface text-foreground hover:border-muted"
                  }`}
                >
                  {a.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-sm font-medium text-foreground block mb-2">Campaign Goal</label>
            <div className="space-y-1.5">
              {GOALS.map((g) => (
                <button
                  key={g.value}
                  onClick={() => setGoal(g.value)}
                  className={`w-full rounded-md border px-3 py-2 text-left text-sm transition-all cursor-pointer ${
                    goal === g.value
                      ? "border-primary bg-[#f0f4ff] text-primary font-medium"
                      : "border-border bg-surface text-foreground hover:border-muted"
                  }`}
                >
                  {g.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-sm font-medium text-foreground block mb-2">Tone</label>
            <div className="space-y-1.5">
              {TONES.map((t) => (
                <button
                  key={t.value}
                  onClick={() => setTone(t.value)}
                  className={`w-full rounded-md border px-3 py-2 text-left text-sm transition-all cursor-pointer ${
                    tone === t.value
                      ? "border-primary bg-[#f0f4ff] text-primary font-medium"
                      : "border-border bg-surface text-foreground hover:border-muted"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      <button
        onClick={handleStart}
        disabled={loading}
        className="bg-primary text-white px-10 py-3.5 rounded-lg text-base font-semibold
                   hover:bg-primary-light transition-colors disabled:opacity-50 cursor-pointer shadow-sm"
      >
        {loading ? "Creating session…" : "Start Briefing"}
      </button>

      <div className="grid grid-cols-4 gap-6 text-sm text-muted max-w-2xl">
        {[
          { step: "1", title: "Brief", desc: "Describe goals via chat" },
          { step: "2", title: "Select", desc: "Approve each claim" },
          { step: "3", title: "Generate", desc: "Build compliant content" },
          { step: "4", title: "Export", desc: "Review, refine & export" },
        ].map((s) => (
          <div key={s.step} className="space-y-1 text-center">
            <div className="text-xl font-bold text-primary opacity-40">{s.step}</div>
            <div className="font-medium text-foreground">{s.title}</div>
            <div className="text-xs">{s.desc}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
