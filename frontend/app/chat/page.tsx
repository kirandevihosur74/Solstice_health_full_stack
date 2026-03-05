"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import { sendChatStream, getMessages, clearMessages } from "@/lib/api";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

type ThinkingState = "idle" | "thinking" | "done";

const CONTENT_LABELS: Record<string, string> = {
  email: "HCP Email",
  banner: "Banner Ad",
  social: "Social Post",
  slide: "Slide Deck",
};

export default function ChatPage() {
  const router = useRouter();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [thinkingState, setThinkingState] = useState<ThinkingState>("idle");
  const [thinkingSeconds, setThinkingSeconds] = useState(0);
  const [thinkingCollapsed, setThinkingCollapsed] = useState(false);
  const streamingRef = useRef(false);
  const thinkingStartRef = useRef(0);
  const thinkingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [contentType, setContentType] = useState("email");

  useEffect(() => {
    const sid = localStorage.getItem("session_id");
    const ct = localStorage.getItem("content_type") || "email";
    if (!sid) {
      console.log("[Chat] No session_id found, redirecting to landing");
      router.replace("/");
      return;
    }
    console.log("[Chat] Loaded session_id=%s, content_type=%s", sid, ct);
    setSessionId(sid);
    setContentType(ct);

    getMessages(sid).then(({ messages: msgs }) => {
      if (msgs.length > 0) {
        console.log("[Chat] Restored %d messages from backend", msgs.length);
        setMessages(msgs.map((m) => ({ role: m.role as "user" | "assistant", content: m.content })));
      }
    }).catch((err) => console.error("[Chat] Failed to load messages:", err));
  }, [router]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, thinkingState]);

  const startThinking = useCallback(() => {
    setThinkingState("thinking");
    setThinkingSeconds(0);
    setThinkingCollapsed(false);
    thinkingStartRef.current = Date.now();
    thinkingTimerRef.current = setInterval(() => {
      setThinkingSeconds(Math.floor((Date.now() - thinkingStartRef.current) / 1000));
    }, 1000);
  }, []);

  const stopThinking = useCallback(() => {
    if (thinkingTimerRef.current) {
      clearInterval(thinkingTimerRef.current);
      thinkingTimerRef.current = null;
    }
    const elapsed = Math.max(1, Math.round((Date.now() - thinkingStartRef.current) / 1000));
    setThinkingSeconds(elapsed);
    setThinkingState("done");

    setTimeout(() => {
      setThinkingCollapsed(true);
    }, 600);
  }, []);

  async function handleSend() {
    if (!input.trim() || !sessionId) return;
    const userMsg = input.trim();
    console.log("[Chat] User sending message: '%s' (%d chars)", userMsg.slice(0, 60), userMsg.length);
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setSending(true);
    streamingRef.current = false;
    startThinking();

    try {
      const fullText = await sendChatStream(sessionId, userMsg, (token) => {
        if (!streamingRef.current) {
          streamingRef.current = true;
          stopThinking();
          setMessages((prev) => [...prev, { role: "assistant", content: token }]);
        } else {
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.role === "assistant") {
              updated[updated.length - 1] = { ...last, content: last.content + token };
            }
            return updated;
          });
        }
      });

      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last?.role === "assistant") {
          updated[updated.length - 1] = { ...last, content: fullText };
        }
        return updated;
      });
      console.log("[Chat] Stream complete: %d chars", fullText.length);
    } catch (err) {
      console.error("[Chat] Send failed:", err);
      stopThinking();
      if (streamingRef.current) {
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last?.role === "assistant") {
            updated[updated.length - 1] = { ...last, content: last.content || "Sorry, something went wrong." };
          }
          return updated;
        });
      } else {
        setMessages((prev) => [...prev, { role: "assistant", content: "Sorry, something went wrong. Is the backend running?" }]);
      }
    } finally {
      setSending(false);
      streamingRef.current = false;
      setTimeout(() => {
        setThinkingState("idle");
        setThinkingCollapsed(false);
      }, 2000);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  if (!sessionId) return null;

  const ctLabel = CONTENT_LABELS[contentType] || contentType;

  return (
    <div className="flex flex-col h-[calc(100vh-120px)]">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold text-primary">Brief your content</h1>
          <p className="text-xs text-muted mt-0.5">
            FRUZAQLA &middot; {ctLabel}
          </p>
        </div>
        <div className="flex gap-2">
          {messages.length > 0 && (
            <button
              onClick={async () => {
                if (!sessionId) return;
                console.log("[Chat] Clearing conversation");
                await clearMessages(sessionId);
                setMessages([]);
              }}
              className="text-sm border border-border text-muted px-4 py-2 rounded-lg hover:bg-red-50 hover:text-red-600 hover:border-red-200 transition-colors cursor-pointer"
            >
              Clear Chat
            </button>
          )}
          <button
            onClick={() => router.push("/preview")}
            className="text-sm bg-primary text-white px-4 py-2 rounded-lg hover:bg-primary-light transition-colors cursor-pointer"
          >
            Continue to Preview &rarr;
          </button>
        </div>
      </div>

      {/* Suggestion chips */}
      {messages.length === 0 && thinkingState === "idle" && (
        <div className="flex flex-wrap gap-2 mb-3">
          {[
            "I need an email targeting oncologists about OS data",
            "Focus on the FRESCO-2 survival results",
            "Lead with mechanism of action",
            "Highlight convenient oral dosing",
          ].map((suggestion) => (
            <button
              key={suggestion}
              onClick={() => setInput(suggestion)}
              className="text-xs border border-border rounded-full px-3 py-1.5 text-muted
                         hover:bg-[#f0f4ff] hover:border-primary hover:text-primary transition-colors cursor-pointer"
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}

      <div className="flex-1 overflow-y-auto border border-border rounded-lg bg-surface p-4 space-y-3">
        {messages.length === 0 && thinkingState === "idle" && (
          <div className="text-center mt-12 space-y-2">
            <p className="text-muted text-sm">
              Tell me about the {ctLabel.toLowerCase()} you want to create for FRUZAQLA.
            </p>
            <p className="text-muted text-xs">
              Try describing the audience, key message, or clinical data you want to highlight.
            </p>
          </div>
        )}
        {messages.map((msg, i) => {
          const isLastAssistant = msg.role === "assistant" && i === messages.length - 1 && thinkingState === "done";

          return (
            <div key={i}>
              {/* "Thought for X seconds" label — above the streaming assistant bubble */}
              {isLastAssistant && (
                <div
                  className={`flex items-center gap-1.5 text-xs text-muted/70 px-1 py-1 mb-1 transition-opacity duration-500 ${
                    thinkingCollapsed ? "opacity-50" : "opacity-100"
                  }`}
                >
                  <svg className="w-3 h-3 text-primary/50" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <span>Thought for {thinkingSeconds} second{thinkingSeconds !== 1 ? "s" : ""}</span>
                </div>
              )}

              <div className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[75%] rounded-lg px-4 py-2.5 text-sm leading-relaxed ${
                    msg.role === "user"
                      ? "bg-primary text-white whitespace-pre-line"
                      : "bg-[#f1f5f9] text-foreground prose prose-sm prose-slate max-w-none"
                  }`}
                >
                  {msg.role === "assistant" ? (
                    <ReactMarkdown
                      components={{
                        p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                        strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                        ul: ({ children }) => <ul className="list-disc pl-4 mb-2">{children}</ul>,
                        ol: ({ children }) => <ol className="list-decimal pl-4 mb-2">{children}</ol>,
                        li: ({ children }) => <li className="mb-0.5">{children}</li>,
                      }}
                    >
                      {msg.content}
                    </ReactMarkdown>
                  ) : (
                    msg.content
                  )}
                </div>
              </div>
            </div>
          );
        })}

        {/* Thinking indicator — bouncing dots while waiting */}
        {thinkingState === "thinking" && (
          <div className="flex justify-start">
            <div className="flex items-center gap-2 text-sm text-muted px-4 py-2 bg-[#f1f5f9] rounded-lg">
              <div className="flex gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
              <span className="animate-pulse">
                Thinking{thinkingSeconds > 0 ? ` (${thinkingSeconds}s)` : ""}…
              </span>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      <div className="mt-3 flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Describe your content needs…"
          className="flex-1 border border-border rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-light"
          disabled={sending}
        />
        <button
          onClick={handleSend}
          disabled={sending || !input.trim()}
          className="bg-primary text-white px-5 py-2.5 rounded-lg font-medium text-sm
                     hover:bg-primary-light transition-colors disabled:opacity-40 cursor-pointer"
        >
          Send
        </button>
      </div>
    </div>
  );
}
