export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const BASE = API_BASE;

function log(tag: string, ...args: unknown[]) {
  const ts = new Date().toISOString().slice(11, 23);
  console.log(`%c[${ts}] %c[API:${tag}]`, "color:#888", "color:#0f4c75;font-weight:bold", ...args);
}

function logWarn(tag: string, ...args: unknown[]) {
  const ts = new Date().toISOString().slice(11, 23);
  console.warn(`[${ts}] [API:${tag}]`, ...args);
}

async function request<T>(path: string, opts?: RequestInit): Promise<T> {
  const method = opts?.method ?? "GET";
  const tag = `${method} ${path}`;
  log(tag, "Sending request…", opts?.body ? `body=${(opts.body as string).length} chars` : "");

  const t0 = performance.now();
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const elapsed = (performance.now() - t0).toFixed(1);

  if (!res.ok) {
    const text = await res.text();
    logWarn(tag, `FAILED ${res.status} in ${elapsed}ms —`, text.slice(0, 200));
    throw new Error(`API ${res.status}: ${text}`);
  }

  const data = await res.json() as T;
  log(tag, `OK ${res.status} in ${elapsed}ms`);
  return data;
}

// ── Types ───────────────────────────────────────────────────────────

export type ContentType = "email" | "banner" | "social";
export type Audience = "hcp" | "patients" | "caregivers" | "payers";
export type CampaignGoal = "awareness" | "education" | "cta" | "launch";
export type Tone = "clinical" | "empathetic" | "urgent" | "informative";

export interface SessionParams {
  content_type: ContentType;
  audience: Audience;
  campaign_goal: CampaignGoal;
  tone: Tone;
}

export interface SessionInfo {
  session_id: string;
  content_type: string;
  audience: string;
  campaign_goal: string;
  tone: string;
}

export interface ClaimItem {
  id: string;
  text: string;
  citation: string;
  source: "clinical_literature" | "prior_approved";
  category: string;
  compliance_status: string;
  approved_date?: string;
}

export interface VersionItem {
  id: string;
  created_at: string;
  html_preview: string;
  revision_number: number;
  content_type: string;
}

export interface VersionDetail {
  id: string;
  created_at: string;
  html: string;
  revision_number: number;
}

export interface ReviewItem {
  check: string;
  status: "pass" | "warn" | "fail";
  detail: string;
}

export interface ComplianceReviewResult {
  overall: "pass" | "warn" | "fail";
  can_export: boolean;
  items: ReviewItem[];
}

export interface ExportPackage {
  html: string;
  metadata: Record<string, unknown>;
  compliance_report: Record<string, unknown>;
}

// ── API calls ───────────────────────────────────────────────────────

export async function createSession(params: SessionParams) {
  log("createSession", `type=${params.content_type}, audience=${params.audience}, goal=${params.campaign_goal}, tone=${params.tone}`);
  const result = await request<SessionInfo>("/session", {
    method: "POST",
    body: JSON.stringify(params),
  });
  log("createSession", `Created session_id=${result.session_id}`);
  return result;
}

export async function getSession(sessionId: string) {
  log("getSession", `session_id=${sessionId}`);
  return request<SessionInfo>(`/session/${sessionId}`);
}

export async function getMessages(sessionId: string) {
  log("getMessages", `session_id=${sessionId}`);
  const result = await request<{ messages: { role: string; content: string }[] }>(
    `/messages?session_id=${sessionId}`
  );
  log("getMessages", `${result.messages.length} messages loaded`);
  return result;
}

export async function clearMessages(sessionId: string) {
  log("clearMessages", `session_id=${sessionId}`);
  const result = await request<{ deleted: number }>(`/messages?session_id=${sessionId}`, {
    method: "DELETE",
  });
  log("clearMessages", `Deleted ${result.deleted} messages`);
  return result;
}

export async function sendChat(sessionId: string, content: string) {
  log("sendChat", `session_id=${sessionId}, content='${content.slice(0, 60)}'`);
  const result = await request<{ assistant_message: string }>("/chat", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, role: "user", content }),
  });
  log("sendChat", `Reply: ${result.assistant_message.length} chars — '${result.assistant_message.slice(0, 80)}…'`);
  return result;
}

const CHAR_DELAY_MS = 18;

export async function sendChatStream(
  sessionId: string,
  content: string,
  onToken: (token: string) => void,
): Promise<string> {
  log("sendChatStream", `session_id=${sessionId}, content='${content.slice(0, 60)}'`);

  const res = await fetch(`${BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, role: "user", content }),
  });

  if (!res.ok) {
    const text = await res.text();
    logWarn("sendChatStream", `FAILED ${res.status}:`, text.slice(0, 200));
    throw new Error(`API ${res.status}: ${text}`);
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let fullText = "";
  let buffer = "";
  const charQueue: string[] = [];
  let draining = false;
  let drainResolve: (() => void) | null = null;

  function drain(): Promise<void> {
    if (draining) return Promise.resolve();
    draining = true;
    return new Promise<void>((resolve) => {
      drainResolve = resolve;
      function step() {
        if (charQueue.length === 0) {
          draining = false;
          resolve();
          drainResolve = null;
          return;
        }
        const ch = charQueue.shift()!;
        onToken(ch);
        setTimeout(step, CHAR_DELAY_MS);
      }
      step();
    });
  }

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      try {
        const data = JSON.parse(line.slice(6));
        if (data.token) {
          for (const ch of data.token) {
            charQueue.push(ch);
          }
        }
        if (data.done) {
          fullText = data.full_text || fullText;
        }
        if (data.error) {
          logWarn("sendChatStream", "Stream error:", data.error);
        }
      } catch {
        // skip malformed SSE lines
      }
    }

    drain();
  }

  if (charQueue.length > 0 || draining) {
    await new Promise<void>((resolve) => {
      const check = setInterval(() => {
        if (charQueue.length === 0 && !draining) {
          clearInterval(check);
          resolve();
        }
      }, 50);
    });
  }

  log("sendChatStream", `Stream complete — ${fullText.length} chars`);
  return fullText;
}

export async function getRecommendedClaims(sessionId: string) {
  log("getClaims", `session_id=${sessionId}`);
  const result = await request<{ claims: ClaimItem[] }>(
    `/claims/recommended?session_id=${sessionId}`
  );
  const categories = result.claims.reduce<Record<string, number>>((acc, c) => {
    acc[c.category] = (acc[c.category] || 0) + 1;
    return acc;
  }, {});
  log("getClaims", `Received ${result.claims.length} claims —`, categories);
  return result;
}

export interface AssetItem {
  asset_id: string;
  filename: string;
  source_doc: string;
  source_page?: string;
  tags: string[];
}

export async function getAssets() {
  log("getAssets", "Fetching approved assets");
  const result = await request<{ assets: AssetItem[] }>("/assets");
  log("getAssets", `${result.assets.length} assets loaded`);
  return result;
}

export async function generateHtml(
  sessionId: string,
  claimIds: string[],
  selectedAssetIds?: string[]
) {
  log("generate", `session_id=${sessionId}, ${claimIds.length} claims, ${selectedAssetIds?.length ?? 0} assets`);
  const result = await request<{ html: string; revision_number: number }>("/generate", {
    method: "POST",
    body: JSON.stringify({
      session_id: sessionId,
      claim_ids: claimIds,
      selected_asset_ids: selectedAssetIds ?? [],
    }),
  });
  log("generate", `Rev ${result.revision_number}, HTML ${result.html.length} chars`);
  return result;
}

export async function editHtml(
  sessionId: string,
  currentHtml: string,
  instruction: string
) {
  log("edit", `session_id=${sessionId}, instruction='${instruction}', html=${currentHtml.length} chars`);
  const result = await request<{ html: string; revision_number: number }>("/edit", {
    method: "POST",
    body: JSON.stringify({
      session_id: sessionId,
      current_html: currentHtml,
      instruction,
    }),
  });
  log("edit", `Rev ${result.revision_number}, HTML ${result.html.length} chars (delta ${result.html.length - currentHtml.length > 0 ? "+" : ""}${result.html.length - currentHtml.length})`);
  return result;
}

export async function runComplianceReview(sessionId: string, claimIds: string[]) {
  log("compliance", `session_id=${sessionId}, ${claimIds.length} claims`);
  const result = await request<ComplianceReviewResult>("/compliance-review", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, claim_ids: claimIds }),
  });
  const counts = { pass: 0, warn: 0, fail: 0 };
  result.items.forEach((i) => counts[i.status]++);
  log("compliance", `Overall=${result.overall}, can_export=${result.can_export} —`, counts);
  return result;
}

export async function exportContent(sessionId: string, claimIds: string[]): Promise<Blob> {
  log("export", `session_id=${sessionId}, ${claimIds.length} claims`);
  const res = await fetch(`${API_BASE}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, claim_ids: claimIds }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Export failed: ${text}`);
  }
  const blob = await res.blob();
  log("export", `Zip received — ${blob.size} bytes`);
  return blob;
}

export async function getVersions(sessionId: string) {
  log("versions", `Listing versions for session_id=${sessionId}`);
  const result = await request<{ versions: VersionItem[] }>(
    `/versions?session_id=${sessionId}`
  );
  log("versions", `${result.versions.length} versions found`);
  return result;
}

export async function clearVersions(sessionId: string) {
  log("clearVersions", `session_id=${sessionId}`);
  const result = await request<{ deleted: number }>(`/versions?session_id=${sessionId}`, {
    method: "DELETE",
  });
  log("clearVersions", `Deleted ${result.deleted} versions`);
  return result;
}

export async function getVersion(versionId: string) {
  log("version", `Loading version_id=${versionId}`);
  const result = await request<VersionDetail>(`/versions/${versionId}`);
  log("version", `Rev ${result.revision_number}, HTML ${result.html.length} chars`);
  return result;
}
