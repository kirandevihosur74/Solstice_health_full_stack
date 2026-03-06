"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  getSession,
  getRecommendedClaims,
  getAssets,
  generateHtml,
  editHtml,
  getVersions,
  getVersion,
  clearVersions,
  runComplianceReview,
  exportContent,
  API_BASE,
  type ClaimItem,
  type AssetItem,
  type VersionItem,
  type ComplianceReviewResult,
} from "@/lib/api";

const CATEGORY_LABELS: Record<string, string> = {
  efficacy: "Efficacy",
  safety: "Safety",
  indication: "Indication",
  dosing: "Dosing",
  mechanism: "Mechanism of Action",
  quality_of_life: "Quality of Life",
};
const CATEGORY_ORDER = ["indication", "efficacy", "mechanism", "dosing", "quality_of_life", "safety"];
const SOURCE_LABELS: Record<string, string> = {
  clinical_literature: "Clinical Literature",
  prior_approved: "Source",
};

function groupBy<T>(arr: T[], key: (item: T) => string): Record<string, T[]> {
  const result: Record<string, T[]> = {};
  for (const item of arr) {
    const k = key(item);
    if (!result[k]) result[k] = [];
    result[k].push(item);
  }
  return result;
}

const STATUS_ICON: Record<string, string> = { pass: "\u2705", warn: "\u26A0\uFE0F", fail: "\u274C" };
const STATUS_BG: Record<string, string> = {
  pass: "bg-green-50 border-green-200",
  warn: "bg-amber-50 border-amber-200",
  fail: "bg-red-50 border-red-200",
};
const STATUS_TEXT: Record<string, string> = {
  pass: "text-green-700",
  warn: "text-amber-700",
  fail: "text-red-700",
};

export default function PreviewPage() {
  const router = useRouter();
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [contentType, setContentType] = useState<string>("email");
  const [claims, setClaims] = useState<ClaimItem[]>([]);
  const [assets, setAssets] = useState<AssetItem[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>([]);
  const [html, setHtml] = useState("");
  const [revision, setRevision] = useState(0);
  const [editInstruction, setEditInstruction] = useState("");
  const [versions, setVersions] = useState<VersionItem[]>([]);
  const [loading, setLoading] = useState("");
  const [review, setReview] = useState<ComplianceReviewResult | null>(null);
  const [showSource, setShowSource] = useState(false);
  const [iframeHeight, setIframeHeight] = useState<number | null>(null);
  const [bannerZoom, setBannerZoom] = useState(100);

  useEffect(() => {
    const sid = localStorage.getItem("session_id");
    if (!sid) {
      console.log("[Preview] No session_id, redirecting to landing");
      router.replace("/");
      return;
    }
    console.log("[Preview] Loaded session_id=%s", sid);
    setSessionId(sid);
  }, [router]);

  const refreshVersions = useCallback(async () => {
    if (!sessionId) return;
    console.log("[Preview] Refreshing version history");
    const { versions: v } = await getVersions(sessionId);
    console.log("[Preview] %d versions loaded", v.length);
    setVersions(v);
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    console.log("[Preview] Fetching session, claims, assets, and versions");
    getSession(sessionId).then((s) => setContentType(s.content_type || "email"));
    getRecommendedClaims(sessionId).then(({ claims: c }) => {
      console.log("[Preview] %d claims loaded", c.length);
      setClaims(c);
    });
    getAssets().then(({ assets: a }) => {
      console.log("[Preview] %d approved assets loaded", a.length);
      setAssets(a);
    });
    refreshVersions();
  }, [sessionId, refreshVersions]);

  useEffect(() => {
    if (!iframeRef.current || !html) return;
    const doc = iframeRef.current.contentDocument;
    if (doc) {
      doc.open();
      doc.write(html);
      doc.close();
      if (contentType !== "banner") {
        const h = doc.documentElement.scrollHeight;
        setIframeHeight(h > 0 ? h : null);
      } else {
        setIframeHeight(null);
      }
    }
  }, [html, contentType]);

  const isBanner = contentType === "banner";

  function toggleClaim(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      const action = next.has(id) ? "deselected" : "selected";
      if (next.has(id)) next.delete(id); else next.add(id);
      console.log("[Preview] Claim %s: %s (now %d selected)", action, id.slice(0, 8), next.size);
      return next;
    });
    setReview(null);
  }
  function selectAll() {
    console.log("[Preview] Select all claims (%d)", claims.length);
    setSelectedIds(new Set(claims.map((c) => c.id)));
    setReview(null);
  }
  function deselectAll() {
    console.log("[Preview] Deselect all claims");
    setSelectedIds(new Set());
    setReview(null);
  }

  async function handleComplianceReview() {
    if (!sessionId || selectedIds.size === 0) return;
    console.log("[Preview] Running compliance review — %d claims", selectedIds.size);
    setReview(null);
    setLoading("compliance");
    try {
      await new Promise((r) => setTimeout(r, 1200));
      const result = await runComplianceReview(sessionId, [...selectedIds]);
      console.log("[Preview] Compliance result: %s, can_export=%s", result.overall, result.can_export);
      setReview(result);
    } catch (err) { console.error("[Preview] Compliance review failed:", err); }
    finally { setLoading(""); }
  }

  async function handleGenerate() {
    if (!sessionId || selectedIds.size === 0) return;
    console.log("[Preview] Generating HTML — %d claims, %d assets", selectedIds.size, selectedAssetIds.length);
    setLoading("generate");
    try {
      await new Promise((r) => setTimeout(r, 1200));
      const { html: h, revision_number } = await generateHtml(
        sessionId,
        [...selectedIds],
        selectedAssetIds
      );
      console.log("[Preview] Generated rev %d, %d chars", revision_number, h.length);
      setHtml(h);
      setRevision(revision_number);
      await refreshVersions();
      console.log("[Preview] Auto-running compliance review after generation");
      const result = await runComplianceReview(sessionId, [...selectedIds]);
      console.log("[Preview] Post-generate compliance: %s", result.overall);
      setReview(result);
    } catch (err) { console.error("[Preview] Generate failed:", err); }
    finally { setLoading(""); }
  }

  async function handleEdit() {
    if (!sessionId || !html || !editInstruction.trim()) return;
    console.log("[Preview] Applying edit: '%s' to rev %d (%d chars)", editInstruction, revision, html.length);
    setLoading("edit");
    try {
      await new Promise((r) => setTimeout(r, 1200));
      const { html: h, revision_number } = await editHtml(sessionId, html, editInstruction);
      console.log("[Preview] Edit result: rev %d, %d chars (delta %+d)", revision_number, h.length, h.length - html.length);
      setHtml(h);
      setRevision(revision_number);
      setEditInstruction("");
      await refreshVersions();
      if (selectedIds.size > 0) {
        console.log("[Preview] Auto-running compliance review after edit");
        const result = await runComplianceReview(sessionId, [...selectedIds]);
        console.log("[Preview] Post-edit compliance: %s", result.overall);
        setReview(result);
      }
    } catch (err) { console.error("[Preview] Edit failed:", err); }
    finally { setLoading(""); }
  }

  async function handleLoadVersion(versionId: string) {
    console.log("[Preview] Loading version %s", versionId);
    setLoading("load");
    try {
      const v = await getVersion(versionId);
      const fromList = versions.find((x) => x.id === versionId);
      if (fromList?.content_type) setContentType(fromList.content_type);
      setHtml(v.html);
      setRevision(v.revision_number);
    } catch (err) { console.error("[Preview] Load version failed:", err); }
    finally { setLoading(""); }
  }

  async function handleClearPreview() {
    if (!sessionId) return;
    console.log("[Preview] Clearing preview and version history");
    setLoading("clear");
    try {
      await clearVersions(sessionId);
      setHtml("");
      setRevision(0);
      setReview(null);
      setVersions([]);
      setEditInstruction("");
      console.log("[Preview] Preview cleared");
    } catch (err) { console.error("[Preview] Clear preview failed:", err); }
    finally { setLoading(""); }
  }

  async function handleExport() {
    if (!sessionId || selectedIds.size === 0) return;
    console.log("[Preview] Exporting content package — rev %d, %d claims", revision, selectedIds.size);
    setLoading("export");
    try {
      const blob = await exportContent(sessionId, [...selectedIds]);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `fruzaqla-export-rev${revision}.zip`;
      a.click();
      URL.revokeObjectURL(url);
      console.log("[Preview] Export complete — zip downloaded");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Export failed";
      console.error("[Preview] Export failed:", msg);
      alert(msg);
    } finally { setLoading(""); }
  }

  if (!sessionId) return null;

  const grouped = groupBy(claims, (c) => c.category);
  const sortedCategories = CATEGORY_ORDER.filter((cat) => grouped[cat]);
  const passCount = review ? review.items.filter((i) => i.status === "pass").length : 0;
  const warnCount = review ? review.items.filter((i) => i.status === "warn").length : 0;
  const failCount = review ? review.items.filter((i) => i.status === "fail").length : 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-primary">Preview &amp; Generate</h1>
          <p className="text-xs text-muted mt-0.5">
            FRUZAQLA &middot; {selectedIds.size} claim{selectedIds.size !== 1 ? "s" : ""} selected
            {selectedAssetIds.length > 0 && <span> &middot; {selectedAssetIds.length} asset{selectedAssetIds.length !== 1 ? "s" : ""}</span>}
            {revision > 0 && <span> &middot; Rev {revision}</span>}
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => router.push("/chat")}
            className="text-sm text-primary-light hover:underline cursor-pointer">&larr; Back to Chat</button>
          {review?.can_export && html && (
            <button onClick={handleExport} disabled={loading === "export"}
              className="text-sm bg-green-600 text-white px-4 py-1.5 rounded-lg hover:bg-green-700 transition-colors cursor-pointer disabled:opacity-50">
              {loading === "export" ? "Exporting…" : "Export Package"}
            </button>
          )}
        </div>
      </div>

      {/* Claims Selection */}
      <section className="bg-surface border border-border rounded-lg p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-sm uppercase tracking-wide text-muted">
            Approved Claims Library
          </h2>
          <div className="flex gap-2 text-xs">
            <button onClick={selectAll} className="text-primary-light hover:underline cursor-pointer">Select all</button>
            <span className="text-border">|</span>
            <button onClick={deselectAll} className="text-primary-light hover:underline cursor-pointer">Clear</button>
            <span className="text-border">|</span>
            <button onClick={() => setShowSource(!showSource)}
              className="text-primary-light hover:underline cursor-pointer">
              {showSource ? "Hide" : "Show"} sources
            </button>
          </div>
        </div>

        {claims.length === 0 ? (
          <p className="text-sm text-muted">Loading claims…</p>
        ) : (
          <div className="space-y-5">
            {sortedCategories.map((cat) => (
              <div key={cat}>
                <h3 className="text-xs font-bold uppercase tracking-wider text-primary mb-2 flex items-center gap-2">
                  <span className={`inline-block w-2 h-2 rounded-full ${
                    cat === "safety" ? "bg-red-400" : cat === "efficacy" ? "bg-green-400" :
                    cat === "indication" ? "bg-blue-400" : "bg-gray-300"
                  }`} />
                  {CATEGORY_LABELS[cat] || cat}
                </h3>
                <ul className="space-y-2">
                  {grouped[cat].map((c) => (
                    <li key={c.id} className={`flex items-start gap-3 rounded-md p-2 transition-colors ${
                      selectedIds.has(c.id) ? "bg-blue-50/60" : ""
                    }`}>
                      <input type="checkbox" checked={selectedIds.has(c.id)}
                        onChange={() => toggleClaim(c.id)}
                        className="mt-1.5 accent-[var(--primary)] cursor-pointer" />
                      <div className="text-sm flex-1">
                        <span className={`leading-relaxed ${selectedIds.has(c.id) ? "text-foreground" : "text-muted"}`}>
                          {c.text}
                        </span>
                        {showSource && (
                          <div className="flex flex-wrap gap-2 mt-1 text-xs items-center">
                            <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                              c.source === "clinical_literature" ? "bg-blue-50 text-blue-700" : "bg-green-50 text-green-700"
                            }`}>{SOURCE_LABELS[c.source] || c.source}</span>
                            <span className="text-muted">{c.citation}</span>
                            {c.approved_date && (
                              <span className="text-muted">Approved: {c.approved_date}</span>
                            )}
                          </div>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}

        {/* Approved Assets Picker */}
        {assets.length > 0 && (
          <div className="mt-5 pt-5 border-t border-border">
            <h3 className="text-xs font-bold uppercase tracking-wider text-primary mb-2">
              Approved Assets
            </h3>
            <p className="text-xs text-muted mb-3">
              Select 1 logo (optional) and/or 1 hero image (optional). Max 2–3 assets. Only approved assets are inserted.
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {assets.map((a) => {
                const isHero = a.tags?.includes("hero") ?? a.filename.toLowerCase().includes("hero");
                const isLogo = a.tags?.includes("logo") ?? a.filename.toLowerCase().includes("logo");
                const role = isHero ? "Hero" : isLogo ? "Logo" : "Asset";
                const selected = selectedAssetIds.includes(a.asset_id);
                return (
                  <label
                    key={a.asset_id}
                    className={`flex flex-col rounded-lg border overflow-hidden cursor-pointer transition-colors ${
                      selected ? "bg-blue-50 border-blue-300 ring-2 ring-blue-200" : "border-border hover:bg-gray-50"
                    }`}
                  >
                    <div className="aspect-video bg-gray-100 flex items-center justify-center p-2">
                      <img
                        src={`${API_BASE}/assets/${a.asset_id}`}
                        alt={a.filename}
                        className="max-w-full max-h-full object-contain"
                        onError={(e) => {
                          (e.target as HTMLImageElement).style.display = "none";
                        }}
                      />
                    </div>
                    <div className="p-2 flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={selected}
                        onChange={() => {
                          setSelectedAssetIds((prev) => {
                            const next = prev.includes(a.asset_id)
                              ? prev.filter((id) => id !== a.asset_id)
                              : prev.length < 3
                                ? [...prev, a.asset_id]
                                : prev;
                            return next;
                          });
                          setReview(null);
                        }}
                        className="accent-[var(--primary)] shrink-0"
                      />
                      <div className="min-w-0 flex-1">
                        <span className="text-xs font-medium text-muted">{role}</span>
                        <span className="text-sm block truncate" title={a.filename}>{a.filename}</span>
                      </div>
                    </div>
                  </label>
                );
              })}
            </div>
          </div>
        )}

        <div className="mt-5 flex items-center gap-3 flex-wrap">
          <button onClick={handleComplianceReview}
            disabled={selectedIds.size === 0 || loading === "compliance"}
            className="border border-primary text-primary px-4 py-2 rounded-lg text-sm font-medium
                       hover:bg-[#f0f4ff] transition-colors disabled:opacity-40 cursor-pointer
                       inline-flex items-center gap-2">
            {loading === "compliance" && (
              <span className="inline-block w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            )}
            {loading === "compliance" ? "Reviewing…" : "Compliance Review"}
          </button>
          <button onClick={handleGenerate}
            disabled={selectedIds.size === 0 || loading === "generate"}
            className="bg-primary text-white px-5 py-2 rounded-lg text-sm font-medium
                       hover:bg-primary-light transition-colors disabled:opacity-40 cursor-pointer
                       inline-flex items-center gap-2">
            {loading === "generate" && (
              <span className="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
            )}
            {loading === "generate" ? "Generating…" : "Generate Content"}
          </button>
        </div>
      </section>

      {/* Compliance Review Panel */}
      {(review || loading === "compliance") && (
        <section className={`border rounded-lg p-5 ${loading === "compliance" ? "bg-slate-50 border-slate-200" : STATUS_BG[review!.overall]}`}>
          {loading === "compliance" ? (
            <div className="flex items-center gap-3 py-4">
              <span className="inline-block w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
              <span className="text-sm text-muted font-medium">Running compliance review…</span>
            </div>
          ) : (
            <>
          <div className="flex items-center justify-between mb-3">
            <h2 className={`font-semibold text-sm uppercase tracking-wide ${STATUS_TEXT[review.overall]}`}>
              Compliance Review — {review.overall === "pass" ? "All Checks Passed" :
                review.overall === "warn" ? "Passed with Warnings" : "Blocking Issues Found"}
            </h2>
            <div className="flex gap-3 text-xs font-medium">
              <span className="text-green-700">{passCount} passed</span>
              {warnCount > 0 && <span className="text-amber-700">{warnCount} warnings</span>}
              {failCount > 0 && <span className="text-red-700">{failCount} failures</span>}
            </div>
          </div>
          <div className="space-y-2">
            {review.items.map((item, i) => (
              <div key={i} className={`flex items-start gap-3 p-2.5 rounded-md border ${STATUS_BG[item.status]}`}>
                <span className="text-base leading-none mt-0.5">{STATUS_ICON[item.status]}</span>
                <div className="flex-1 min-w-0">
                  <div className={`text-xs font-semibold ${STATUS_TEXT[item.status]}`}>{item.check}</div>
                  <div className="text-xs text-foreground mt-0.5">{item.detail}</div>
                </div>
              </div>
            ))}
          </div>
          {!review.can_export && (
            <p className="mt-3 text-xs text-red-700 font-medium">
              Export blocked — resolve all red items before exporting.
            </p>
          )}
          {review.can_export && html && (
            <div className="mt-3 flex items-center gap-3">
              <button onClick={handleExport} disabled={loading === "export"}
                className="bg-green-600 text-white px-5 py-2 rounded-lg text-sm font-medium
                           hover:bg-green-700 transition-colors cursor-pointer disabled:opacity-50">
                {loading === "export" ? "Exporting…" : "Export Content Package"}
              </button>
              <span className="text-xs text-green-700">Includes HTML, metadata, compliance report &amp; asset manifest</span>
            </div>
          )}
            </>
          )}
        </section>
      )}

      {/* HTML Preview */}
      {html && (
        <section className="bg-surface border border-border rounded-lg overflow-hidden">
          <div className="px-5 py-3 border-b border-border flex items-center justify-between flex-wrap gap-2">
            <h2 className="font-semibold text-sm uppercase tracking-wide text-muted">
              Content Preview
              {revision > 0 && (
                <span className="ml-2 text-xs font-normal text-primary bg-blue-50 px-2 py-0.5 rounded">Rev {revision}</span>
              )}
              {isBanner && (
                <span className="ml-2 text-xs font-normal text-muted">728×90</span>
              )}
            </h2>
            <div className="flex items-center gap-2">
              {isBanner && (
                <div className="flex items-center gap-1">
                  <span className="text-xs text-muted">Zoom:</span>
                  {[100, 150, 200].map((z) => (
                    <button
                      key={z}
                      onClick={() => setBannerZoom(z)}
                      className={`text-xs px-2 py-1 rounded transition-colors ${
                        bannerZoom === z
                          ? "bg-primary text-white"
                          : "bg-gray-100 text-muted hover:bg-gray-200"
                      }`}
                    >
                      {z}%
                    </button>
                  ))}
                </div>
              )}
              <span className="text-xs text-muted">Sandboxed iframe</span>
            </div>
          </div>
          <div
            className="flex items-center justify-center bg-[#f6f7fb]"
            style={{
              minHeight: isBanner ? Math.max(220, 90 * (bannerZoom / 100) + 60) : 120,
              padding: isBanner ? 24 : 16,
            }}
          >
            {isBanner ? (
              <div
                className="border border-gray-200 bg-white shadow-sm overflow-hidden"
                style={{
                  width: 728,
                  height: 90,
                  transform: `scale(${bannerZoom / 100})`,
                  transformOrigin: "center center",
                }}
              >
                <iframe
                  ref={iframeRef}
                  title="HTML Preview"
                  className="border-0 block"
                  style={{ width: 728, height: 90 }}
                  sandbox="allow-same-origin"
                />
              </div>
            ) : (
              <div className="w-full max-w-2xl flex justify-center">
                <iframe
                  ref={iframeRef}
                  title="HTML Preview"
                  className="w-full border border-gray-200 bg-white shadow-sm"
                  style={{
                    minHeight: iframeHeight ?? 560,
                    height: iframeHeight ?? undefined,
                  }}
                  sandbox="allow-same-origin"
                />
              </div>
            )}
          </div>
        </section>
      )}

      {/* Edit Request */}
      {html && (
        <section className="bg-surface border border-border rounded-lg p-5">
          <h2 className="font-semibold text-sm uppercase tracking-wide text-muted mb-2">
            Request a Revision
          </h2>
          <p className="text-xs text-muted mb-3">
            Describe changes in natural language. Compliance re-checks automatically after each edit.
          </p>
          <div className="flex gap-2">
            <input type="text" value={editInstruction}
              onChange={(e) => setEditInstruction(e.target.value)}
              placeholder='e.g. "Move safety section above efficacy"'
              className="flex-1 border border-border rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-light"
              onKeyDown={(e) => { if (e.key === "Enter") handleEdit(); }} />
            <button onClick={handleEdit}
              disabled={!editInstruction.trim() || loading === "edit"}
              className="bg-accent text-white px-5 py-2 rounded-lg text-sm font-medium
                         hover:opacity-90 transition-opacity disabled:opacity-40 cursor-pointer
                         inline-flex items-center gap-2">
              {loading === "edit" && (
                <span className="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              )}
              {loading === "edit" ? "Applying…" : "Apply Revision"}
            </button>
          </div>
          <div className="flex flex-wrap gap-2 mt-3">
            {[
              "Move safety above efficacy",
              "Make it shorter",
              "Bold the first claim",
              "Remove CTA button",
              "Add CTA button",
            ].map((hint) => (
              <button key={hint} onClick={() => setEditInstruction(hint)}
                className="text-xs border border-border rounded-full px-3 py-1 text-muted
                           hover:bg-[#fff8f0] hover:border-accent hover:text-accent transition-colors cursor-pointer">
                {hint}
              </button>
            ))}
          </div>
        </section>
      )}

      {/* Version History */}
      <section className="bg-surface border border-border rounded-lg p-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-semibold text-sm uppercase tracking-wide text-muted">
            Version History
          </h2>
          <button
            onClick={handleClearPreview}
            disabled={loading === "clear"}
            className="text-sm text-amber-600 hover:text-amber-700 hover:underline cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {loading === "clear" ? "Clearing…" : "Clear Versions"}
          </button>
        </div>
        {versions.length === 0 ? (
          <p className="text-sm text-muted">No versions yet. Generate content to create your first version.</p>
        ) : (
          <ul className="space-y-2">
            {versions.map((v) => (
              <li key={v.id}
                className={`flex items-center justify-between border rounded-md px-4 py-3 transition-colors ${
                  revision === v.revision_number ? "border-primary bg-blue-50/50" : "border-border hover:bg-[#fafbfc]"
                }`}>
                <div className="text-sm flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-xs font-mono bg-blue-50 text-primary px-1.5 py-0.5 rounded">
                      Rev {v.revision_number}
                    </span>
                    <span className="text-muted text-xs">
                      {v.created_at ? new Date(v.created_at).toLocaleString() : ""}
                    </span>
                    <span className="text-xs text-muted uppercase">{v.content_type}</span>
                  </div>
                  <span className="text-foreground text-xs truncate block">{v.html_preview}</span>
                </div>
                <button onClick={() => handleLoadVersion(v.id)} disabled={loading === "load"}
                  className="text-xs text-primary-light hover:underline cursor-pointer ml-3 shrink-0">
                  {revision === v.revision_number ? "Current" : "Load"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
