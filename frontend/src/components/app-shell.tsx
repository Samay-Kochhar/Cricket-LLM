"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { ChatResponseSections } from "@/components/results/chat-response-sections";
import { CompactDataTable } from "@/components/results/compact-data-table";
import { hasSemanticTrace } from "@/components/results/semantic-debug-trace";
import { SessionList } from "@/components/session-list";
import { useAtlasChat } from "@/hooks/use-atlas-chat";
import type { ChatHistoryTurn, QueryResponse, TableBlock } from "@/lib/api-types";
import {
  createAtlasMessage,
  createThread,
  prepareAtlasLaunchState,
  saveActiveThreadId,
  saveThreads,
  type AtlasMessage,
  type AtlasThread,
} from "@/lib/atlas-thread-store";
import { consumePendingAtlasPrompt, saveWorkbenchContext } from "@/lib/workbench-context-store";

const VERIFIED_FOLLOW_UPS = new Set([
  "Compare the same players in powerplay, middle, and death overs.",
]);

function buildHistory(messages: AtlasMessage[]): ChatHistoryTurn[] {
  return messages.map((message) => ({
    role: message.role === "assistant" ? "assistant" : "user",
    content: message.content,
  }));
}

function latestConversationState(messages: AtlasMessage[]) {
  return [...messages]
    .reverse()
    .find((message) => message.reply?.conversation_state)?.reply?.conversation_state ?? null;
}

function verifiedFollowUps(message: AtlasMessage): string[] {
  return (message.reply?.suggestions ?? []).filter((suggestion) => VERIFIED_FOLLOW_UPS.has(suggestion));
}

function reorderThreads(threads: AtlasThread[], activeId: string): AtlasThread[] {
  const activeThread = threads.find((thread) => thread.id === activeId);
  if (!activeThread) {
    return threads;
  }
  return [activeThread, ...threads.filter((thread) => thread.id !== activeId)];
}

function visibleMessageContent(message: AtlasMessage): string {
  const firstTableTitle = message.reply?.query_response?.tables?.[0]?.title;
  if (message.role !== "assistant" || !firstTableTitle) {
    return message.content;
  }
  const tableStart = message.content.indexOf(`\n\n${firstTableTitle}\n`);
  return tableStart >= 0 ? message.content.slice(0, tableStart) : message.content;
}

function questionWithMinimumBalls(
  question: string,
  minimumBalls: number,
  sampleUnit: "balls" | "legal balls",
): string {
  const withoutExistingThreshold = question
    .replace(/\bminimum\s+\d+\s+(?:legal\s+balls|balls|deliveries)\b/gi, "")
    .replace(/\s+([,?.!])/g, "$1")
    .replace(/[,?.!\s]+$/, "")
    .trim();
  return `${withoutExistingThreshold}, minimum ${minimumBalls} ${sampleUnit}`;
}

function ChatTablePreview({
  result,
  onMinimumBallsApply,
}: {
  result: QueryResponse;
  onMinimumBallsApply: (
    minimumBalls: number,
    sampleUnit: "balls" | "legal balls",
  ) => Promise<void> | void;
}) {
  if (!result.tables.length) {
    return null;
  }

  return (
    <div className="chat-table-preview">
      {result.tables.slice(0, 4).map((table) => (
        <ChatTableCard key={table.title} onMinimumBallsApply={onMinimumBallsApply} table={table} />
      ))}
    </div>
  );
}

function ChatTableCard({
  table,
  onMinimumBallsApply,
}: {
  table: TableBlock;
  onMinimumBallsApply: (
    minimumBalls: number,
    sampleUnit: "balls" | "legal balls",
  ) => Promise<void> | void;
}) {
  return (
    <section className="chat-table-card">
      <div className="panel-heading">
        <span className="eyebrow">ODI database</span>
        <h3 className="card-title">{table.title}</h3>
      </div>
      <CompactDataTable onMinimumBallsApply={onMinimumBallsApply} table={table} />
    </section>
  );
}

export function AppShell() {
  const router = useRouter();
  const [threads, setThreads] = useState<AtlasThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [showPolicy, setShowPolicy] = useState(false);
  const [expandedEvidenceMessageId, setExpandedEvidenceMessageId] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const { error, isLoading, loadingLabel, sendMessage } = useAtlasChat();

  useEffect(() => {
    const launched = prepareAtlasLaunchState();
    setThreads(launched.threads);
    setActiveThreadId(launched.activeThreadId);
    const pendingPrompt = consumePendingAtlasPrompt();
    if (pendingPrompt) {
      setInput(pendingPrompt);
    }
  }, []);

  const activeThread = useMemo(
    () => threads.find((thread) => thread.id === activeThreadId) ?? null,
    [activeThreadId, threads],
  );

  useEffect(() => {
    const element = listRef.current;
    if (element) {
      element.scrollTop = element.scrollHeight;
    }
  }, [activeThread?.messages.length, isLoading]);

  function updateThreads(nextThreads: AtlasThread[]) {
    setThreads(nextThreads);
    saveThreads(nextThreads);
  }

  function handleNewThread() {
    const next = [createThread("New Atlas thread"), ...threads];
    updateThreads(next);
    setActiveThreadId(next[0].id);
    saveActiveThreadId(next[0].id);
    setInput("");
  }

  function handleSelectThread(threadId: string) {
    setActiveThreadId(threadId);
    saveActiveThreadId(threadId);
    setExpandedEvidenceMessageId(null);
    setInput("");
  }

  function handleDeleteThread(threadId: string) {
    const remaining = threads.filter((thread) => thread.id !== threadId);
    const nextThreads = remaining.length ? remaining : [createThread("New Atlas thread")];
    const nextActiveId =
      activeThreadId === threadId
        ? nextThreads[0].id
        : activeThreadId && nextThreads.some((thread) => thread.id === activeThreadId)
          ? activeThreadId
          : nextThreads[0].id;
    updateThreads(nextThreads);
    setActiveThreadId(nextActiveId);
    saveActiveThreadId(nextActiveId);
    setExpandedEvidenceMessageId(null);
    setInput("");
  }

  function handleClearThreads() {
    const fresh = createThread("New Atlas thread");
    updateThreads([fresh]);
    setActiveThreadId(fresh.id);
    saveActiveThreadId(fresh.id);
    setExpandedEvidenceMessageId(null);
    setInput("");
  }

  async function handleSend(text: string) {
    if (!activeThread) {
      return;
    }
    const trimmed = text.trim();
    if (!trimmed || isLoading) {
      return;
    }

    const userMessage = createAtlasMessage("user", trimmed);
    const updatedThread: AtlasThread = {
      ...activeThread,
      title:
        activeThread.messages.length === 0 || activeThread.title === "New Atlas thread"
          ? trimmed.slice(0, 56)
          : activeThread.title,
      updatedAt: new Date().toISOString(),
      messages: [...activeThread.messages, userMessage],
    };
    const optimisticThreads = reorderThreads(
      threads.map((thread) => (thread.id === activeThread.id ? updatedThread : thread)),
      updatedThread.id,
    );
    updateThreads(optimisticThreads);
    saveActiveThreadId(updatedThread.id);
    setInput("");

    try {
      const reply = await sendMessage(trimmed, buildHistory(activeThread.messages), {
        conversationState: latestConversationState(activeThread.messages),
      });
      const assistantMessage = createAtlasMessage("assistant", reply.message, reply);
      const finalThread: AtlasThread = {
        ...updatedThread,
        updatedAt: new Date().toISOString(),
        messages: [...updatedThread.messages, assistantMessage],
      };
      updateThreads(
        reorderThreads(
          optimisticThreads.map((thread) => (thread.id === finalThread.id ? finalThread : thread)),
          finalThread.id,
        ),
      );
      saveActiveThreadId(finalThread.id);
    } catch {
      const failure = createAtlasMessage(
        "assistant",
        "Atlas could not answer right now. Check the backend logs or Gemini configuration and try again.",
      );
      const finalThread: AtlasThread = {
        ...updatedThread,
        updatedAt: new Date().toISOString(),
        messages: [...updatedThread.messages, failure],
      };
      updateThreads(
        reorderThreads(
          optimisticThreads.map((thread) => (thread.id === finalThread.id ? finalThread : thread)),
          finalThread.id,
        ),
      );
      saveActiveThreadId(finalThread.id);
    }
  }

  async function handleRefineMessage(
    threadId: string,
    messageId: string,
    originalQuestion: string,
    minimumBalls: number,
    sampleUnit: "balls" | "legal balls",
  ) {
    const refinedQuestion = questionWithMinimumBalls(originalQuestion, minimumBalls, sampleUnit);
    const reply = await sendMessage(refinedQuestion, [], { silent: true });

    setThreads((currentThreads) => {
      const nextThreads = currentThreads.map((thread) => {
        if (thread.id !== threadId) {
          return thread;
        }
        return {
          ...thread,
          updatedAt: new Date().toISOString(),
          messages: thread.messages.map((message) =>
            message.id === messageId
              ? { ...message, content: reply.message, reply }
              : message,
          ),
        };
      });
      saveThreads(nextThreads);
      return nextThreads;
    });
  }

  function handleComposerKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void handleSend(input);
    }
  }

  function handleOpenWorkbench(message: AtlasMessage) {
    const query = message.reply?.query_response?.interpretation.original_question ?? message.content;
    const subject = message.reply?.query_response?.interpretation.entities?.[0] ?? null;
    saveWorkbenchContext({
      source: "atlas",
      query,
      subject,
      threadId: activeThreadId,
    });
    router.push("/workbench");
  }

  return (
    <main className="atlas-chat-shell">
      <header className="atlas-chat-topbar">
        <div>
          <div className="brand-kicker">CricAtlas</div>
          <h1 className="atlas-brand">Atlas</h1>
          <p className="muted-copy">Talk to the ODI analyst, then open the evidence below each answer.</p>
        </div>
        <div className="atlas-topbar-actions">
          <nav className="atlas-nav" aria-label="Primary">
            <Link className="atlas-nav-link is-active" href="/">
              Atlas
            </Link>
            <Link className="atlas-nav-link" href="/workbench">
              Workbench
            </Link>
          </nav>
          <button
            aria-expanded={showPolicy}
            className="ghost-button atlas-policy-toggle"
            onClick={() => setShowPolicy((current) => !current)}
            type="button"
          >
            {showPolicy ? "Hide policy" : "Policy"}
          </button>
        </div>
      </header>

      {showPolicy ? (
        <section className="panel atlas-policy-panel">
          <div className="panel-heading">
            <span className="eyebrow">Atlas policy</span>
            <span className="chip">Collapsed by default</span>
          </div>
          <p className="muted-copy">
            Atlas uses Gemini to shape answers. ODI database evidence stays primary. Web context is
            allowed for definitions, recent questions, and supporting context, never to replace
            local statistics.
          </p>
        </section>
      ) : null}

      <div className="atlas-chat-grid">
        <aside className="atlas-thread-rail">
          <section className="panel rail-panel">
            <div className="panel-heading">
              <span className="eyebrow">History</span>
              <div className="rail-actions">
                <button className="ghost-button" onClick={handleClearThreads} type="button">
                  Clear
                </button>
                <button className="ghost-button" onClick={handleNewThread} type="button">
                  New
                </button>
              </div>
            </div>
            <SessionList
              activeSessionId={activeThreadId}
              onDeleteSession={handleDeleteThread}
              onSelectSession={handleSelectThread}
              sessions={threads.map((thread) => ({
                id: thread.id,
                title: thread.title,
                createdAt: thread.createdAt,
                updatedAt: thread.updatedAt,
              }))}
            />
          </section>
        </aside>

        <section className={`atlas-chat-main panel ${activeThread?.messages.length ? "" : "is-empty"}`}>
          <div className="atlas-chat-header">
            <div>
              <span className="eyebrow">Atlas chat</span>
              <h2 className="section-title">{activeThread?.title ?? "New Atlas thread"}</h2>
            </div>
            <button
              aria-expanded={showPolicy}
              className="ghost-button atlas-policy-toggle compact"
              onClick={() => setShowPolicy((current) => !current)}
              type="button"
            >
              {showPolicy ? "Close details" : "Details"}
            </button>
          </div>

          <div className="atlas-chat-log" ref={listRef}>
            {activeThread?.messages.length ? (
              activeThread.messages.map((message) => (
                <article
                  className={message.role === "assistant" ? "chat-turn assistant" : "chat-turn user"}
                  key={message.id}
                >
                  <div className="chat-bubble">
                    <div className="chat-role">{message.role === "assistant" ? "Atlas" : "You"}</div>
                    <p>{visibleMessageContent(message)}</p>
                    {message.role === "assistant" && message.reply?.activity_trace?.length ? (
                      <div className="chat-activity-row">
                        {message.reply.activity_trace.map((item) => (
                          item === "ODI database" && message.reply?.query_response ? (
                            <button
                              aria-expanded={expandedEvidenceMessageId === message.id}
                              className="chip chip-button"
                              key={`${message.id}-${item}`}
                              onClick={() =>
                                setExpandedEvidenceMessageId((current) =>
                                  current === message.id ? null : message.id,
                                )
                              }
                              type="button"
                            >
                              {expandedEvidenceMessageId === message.id ? "Hide ODI database" : item}
                            </button>
                          ) : (
                            <span className="chip" key={`${message.id}-${item}`}>
                              {item}
                            </span>
                          )
                        ))}
                      </div>
                    ) : null}
                    {message.role === "assistant" && hasSemanticTrace(message.reply?.query_response) ? (
                      <div className="chat-activity-row">
                        <button
                          aria-expanded={expandedEvidenceMessageId === message.id}
                          className="chip chip-button"
                          onClick={() =>
                            setExpandedEvidenceMessageId((current) =>
                              current === message.id ? null : message.id,
                            )
                          }
                          type="button"
                        >
                          {expandedEvidenceMessageId === message.id ? "Hide debug trace" : "Debug trace"}
                        </button>
                      </div>
                    ) : null}
                  </div>

                  {message.role === "assistant" && message.reply?.clarification_options?.length ? (
                    <div className="turn-suggestions" aria-label="Clarification options">
                      {message.reply.clarification_options.map((option) => (
                        <button
                          className="suggestion-chip"
                          key={option.message}
                          onClick={() => void handleSend(option.message)}
                          type="button"
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>
                  ) : null}

                  {message.role === "assistant" && verifiedFollowUps(message).length ? (
                    <div className="turn-suggestions" aria-label="Suggested follow-ups">
                      {verifiedFollowUps(message).map((suggestion) => (
                        <button
                          className="suggestion-chip"
                          key={suggestion}
                          onClick={() => void handleSend(suggestion)}
                          type="button"
                        >
                          {suggestion}
                        </button>
                      ))}
                    </div>
                  ) : null}

                  {message.role === "assistant" && message.reply?.query_response ? (
                    <div className="chat-attachments">
                      <ChatTablePreview
                        onMinimumBallsApply={async (minimumBalls, sampleUnit) => {
                          const question = message.reply?.query_response?.interpretation.original_question;
                          if (question) {
                            await handleRefineMessage(
                              activeThread.id,
                              message.id,
                              question,
                              minimumBalls,
                              sampleUnit,
                            );
                          }
                        }}
                        result={message.reply.query_response}
                      />
                      <div className="chat-attachment-actions">
                        <button className="ghost-button" onClick={() => handleOpenWorkbench(message)} type="button">
                          Go to Workbench
                        </button>
                      </div>
                      {expandedEvidenceMessageId === message.id ? (
                        <ChatResponseSections result={message.reply.query_response} />
                      ) : null}
                    </div>
                  ) : null}
                </article>
              ))
            ) : (
              <section className="atlas-empty-state">
                <span className="eyebrow">Start here</span>
                <h2 className="atlas-empty-title">Ask Atlas like you would ask an analyst.</h2>
                <p className="muted-copy">
                  Atlas can handle database-backed ODI questions, normal cricket conversation, and
                  fuzzy player names when confidence is high.
                </p>
              </section>
            )}

            {isLoading ? (
              <article className="chat-turn assistant">
                <div className="chat-bubble typing">
                  <div className="chat-role">Atlas</div>
                  <p>{loadingLabel ?? "Atlas is thinking through the ODI evidence..."}</p>
                </div>
              </article>
            ) : null}

            {error ? <p className="muted-copy chat-error">{error}</p> : null}
          </div>

          <form
            className="atlas-composer"
            onSubmit={(event) => {
              event.preventDefault();
              void handleSend(input);
            }}
          >
            <textarea
              disabled={isLoading}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={handleComposerKeyDown}
              placeholder="Ask Atlas about a player, matchup, venue, or just talk cricket..."
              value={input}
            />
            <div className="atlas-composer-actions">
              <span className="muted-copy">Enter to send | Shift+Enter for a new line</span>
              <button className="primary-button atlas-send" disabled={!input.trim() || isLoading} type="submit">
                Send
              </button>
            </div>
          </form>
        </section>
      </div>
    </main>
  );
}
