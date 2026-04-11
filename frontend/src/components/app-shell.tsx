"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { SessionList } from "@/components/session-list";
import { useAtlasChat } from "@/hooks/use-atlas-chat";
import type { ChatHistoryTurn } from "@/lib/api-types";
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

const EMPTY_THREAD_SUGGESTIONS = [
  "Compare Virat Kohli at number 3 vs opening in ODIs",
  "Where does Hardik Pandya score the most and on which shots?",
  "Does Shreyas Iyer still struggle against the short ball after 2023?",
  "Talk me through how to judge a batter's weakness against spin",
];

function buildHistory(messages: AtlasMessage[]): ChatHistoryTurn[] {
  return messages.map((message) => ({
    role: message.role === "assistant" ? "assistant" : "user",
    content: message.content,
  }));
}

function reorderThreads(threads: AtlasThread[], activeId: string): AtlasThread[] {
  const activeThread = threads.find((thread) => thread.id === activeId);
  if (!activeThread) {
    return threads;
  }
  return [activeThread, ...threads.filter((thread) => thread.id !== activeId)];
}

export function AppShell() {
  const router = useRouter();
  const [threads, setThreads] = useState<AtlasThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [showPolicy, setShowPolicy] = useState(false);
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
      const reply = await sendMessage(trimmed, buildHistory(activeThread.messages));
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

  const suggestedPrompts =
    activeThread && activeThread.messages.length === 0 ? EMPTY_THREAD_SUGGESTIONS : [];

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
              <button className="ghost-button" onClick={handleNewThread} type="button">
                New
              </button>
            </div>
            <SessionList
              activeSessionId={activeThreadId}
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

        <section className="atlas-chat-main panel">
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
                    <p>{message.content}</p>
                    {message.role === "assistant" && message.reply?.activity_trace?.length ? (
                      <div className="chat-activity-row">
                        {message.reply.activity_trace.map((item) => (
                          <span className="chip" key={`${message.id}-${item}`}>
                            {item}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>

                  {message.role === "assistant" && message.reply?.suggestions?.length ? (
                    <div className="turn-suggestions">
                      {message.reply.suggestions.map((suggestion) => (
                        <button
                          className="suggestion-chip"
                          key={suggestion}
                          onClick={() => setInput(suggestion)}
                          type="button"
                        >
                          {suggestion}
                        </button>
                      ))}
                    </div>
                  ) : null}

                  {message.role === "assistant" && message.reply?.query_response ? (
                    <div className="chat-attachments">
                      <div className="chat-attachment-actions">
                        <button className="ghost-button" onClick={() => handleOpenWorkbench(message)} type="button">
                          Go to Workbench
                        </button>
                      </div>
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

          {suggestedPrompts.length > 0 ? (
            <div className="atlas-suggestions" aria-label="Suggested prompts">
              {suggestedPrompts.map((suggestion) => (
                <button
                  className="suggestion-chip"
                  key={suggestion}
                  onClick={() => setInput(suggestion)}
                  type="button"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          ) : null}

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
