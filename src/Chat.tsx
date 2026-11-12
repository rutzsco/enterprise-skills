import { ArrowDownToLine, ArrowRight, ArrowUp, BookOpen, Check, CircleDot, GitBranch, Layers3, MessageSquarePlus, Search, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, ApiError, errorMessage } from "./api";
import { ErrorNotice, MarkdownText, Spinner, ToolTrace } from "./components";
import type { ChatReply, ServiceStatus, SkillMetadata, ToolEvent } from "./types";

interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "error";
  text: string;
  events?: ToolEvent[];
  skills?: SkillMetadata[];
}

const suggestions = [
  { category: "Finance", title: "Route a software purchase", prompt: "Who needs to approve a $6,000 annual software purchase that handles customer data?" },
  { category: "Operations", title: "Respond to an outage", prompt: "A core workflow is down for 30% of customers with no workaround. What should we do?" },
  { category: "Customer success", title: "Handle a service credit", prompt: "A customer requests a $450 service credit. Who approves it, and how should we reply?" },
];

export function ChatPage({ status, skills, onSetup, openSkill, refresh }: {
  status: ServiceStatus; skills: SkillMetadata[]; onSetup: () => void;
  openSkill: (id: string) => void; refresh: () => Promise<void>;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [loaded, setLoaded] = useState<SkillMetadata[]>([]);
  const conversation = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (conversation.current) conversation.current.scrollTop = conversation.current.scrollHeight;
  }, [messages, busy]);

  async function send() {
    const message = draft.trim();
    if (!message || busy || blocked || !status.configured) return;
    setMessages((items) => [...items, { id: crypto.randomUUID(), role: "user", text: message }]);
    setDraft("");
    setBusy(true);
    setLoaded([]);
    try {
      const reply = await api<ChatReply>("/api/chat", "POST", { message, session_id: sessionId });
      setSessionId(reply.session_id);
      setLoaded(reply.loaded_skills);
      setMessages((items) => [...items, { id: crypto.randomUUID(), role: "assistant", text: reply.answer, events: reply.events, skills: reply.loaded_skills }]);
    } catch (failure) {
      const events = failure instanceof ApiError ? failure.events : [];
      setMessages((items) => [...items, { id: crypto.randomUUID(), role: "error", text: errorMessage(failure), events }]);
      if (failure instanceof ApiError && failure.resetRequired) setBlocked(true);
    } finally {
      setBusy(false);
      void refresh();
    }
  }

  function newChat() {
    setMessages([]);
    setSessionId(null);
    setBlocked(false);
    setLoaded([]);
  }

  return <>
    <div className="page-heading"><div><h1>Expertise, when you need it.</h1><p>A conversation backed by your team's knowledge, not a bigger prompt.</p></div><button className="button secondary" onClick={newChat} disabled={busy || messages.length === 0}><MessageSquarePlus size={16} />New chat</button></div>
    {!status.configured && <div className="connection-banner"><span className="banner-icon"><CircleDot size={19} /></span><div><strong>Your library is ready. Connect your agent.</strong><p>Add your Azure Foundry configuration to enable real chat and skill selection.</p></div><button onClick={onSetup}>Set up Foundry <ArrowRight size={15} /></button></div>}
    <div className="chat-layout">
      <div className="chat-panel">
        <div className="panel-title"><span><span className="small-brand"><Layers3 size={15} /></span>Memory assistant</span><span className="panel-label">SKILL-AWARE CHAT</span></div>
        <div className="conversation" ref={conversation} aria-live="polite" aria-busy={busy}>
          {messages.length === 0 ? <div className="chat-welcome">
            <div className="welcome-art" aria-hidden="true"><div className="orbit orbit-one" /><div className="orbit orbit-two" /><span className="floating-icon floating-one"><BookOpen size={16} /></span><span className="floating-icon floating-two"><Search size={16} /></span><span className="welcome-mark"><Layers3 size={35} strokeWidth={1.5} /></span><span className="sparkle"><Sparkles size={16} /></span></div>
            <span className="tiny-label">YOUR TEAM'S KNOW-HOW, ON DEMAND</span>
            <h2>What does your team know?</h2>
            <p>Ask a question. Your agent finds the right skill,<br className="desktop-break" /> loads its current guidance, and puts it to work.</p>
            <div className="suggestion-grid">{suggestions.map((suggestion) => <button key={suggestion.category} className="suggestion-card" onClick={() => { setDraft(suggestion.prompt); composer.current?.focus(); }}>
              <span>{suggestion.category}</span><strong>{suggestion.title}</strong><ArrowRight size={15} />
            </button>)}</div>
          </div> : <div className="message-list">{messages.map((message) => <article key={message.id} className={`message ${message.role}`}>
            {message.role !== "user" && <span className="message-avatar"><Layers3 size={17} /></span>}
            <div className="message-content">
              <span className="message-author">{message.role === "user" ? "You" : message.role === "error" ? "Run did not complete" : "Memory assistant"}</span>
              {message.events && <ToolTrace events={message.events} />}
              {message.role === "error" ? <ErrorNotice message={message.text} /> : <MarkdownText>{message.text}</MarkdownText>}
              {message.role === "assistant" && <div className="answer-sources">
                {message.skills?.length ? message.skills.map((skill) => <button key={`${skill.id}-${skill.version}`} onClick={() => openSkill(skill.id)}><BookOpen size={12} />{skill.name}<span>v{skill.version}</span></button>) : <span>No skill was loaded for this answer.</span>}
              </div>}
            </div>
          </article>)}</div>}
          {busy && <div className="thinking"><span className="message-avatar"><Layers3 size={17} /></span><Spinner label="Waiting for the Foundry agent..." /><span>Actual tool activity appears with the result.</span></div>}
        </div>
        {blocked && <div className="restart-banner">This run cannot safely continue.<button onClick={newChat}>Start a new conversation <ArrowRight size={14} /></button></div>}
        <form className="composer" onSubmit={(event) => { event.preventDefault(); void send(); }}>
          <div className="composer-input"><textarea ref={composer} value={draft} maxLength={8000} rows={2} placeholder="Ask a question that needs your team's expertise..." aria-label="Message to the memory assistant" disabled={busy || blocked} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send(); }
          }} /><button className="send-button" aria-label="Send message" title={!status.configured ? "Configure Azure Foundry first" : "Send message"} type="submit" disabled={!draft.trim() || busy || blocked || !status.configured}><ArrowUp size={19} /></button></div>
          <div className="composer-footnote"><span><span className={`status-dot ${status.configured ? "green" : ""}`} />{status.configured ? "Azure Foundry Agent Service" : "Live chat requires Foundry setup"}</span><span>{status.configured ? "Shift + Enter for a new line" : "No simulated answers"}</span></div>
        </form>
      </div>

      <aside className="context-column">
        <div className="context-card"><div className="card-title"><h3>On-demand context</h3><span className="number-pill">{loaded.length}</span></div>
          {loaded.length ? <div className="loaded-skills">{loaded.map((skill) => <div key={skill.id}><span className="loaded-check"><Check size={14} /></span><div><strong>{skill.name}</strong><small>Loaded v{skill.version} for the last answer</small></div></div>)}</div> : <div className="context-empty"><ArrowDownToLine size={24} strokeWidth={1.5} /><p>No skills loaded yet</p><span>Only the expertise your agent requests will appear here.</span></div>}
          <div className="context-note"><GitBranch size={14} /><span>No full-library prompt injection.</span></div>
        </div>
        <div className="context-card"><div className="card-title"><h3>Published library</h3><span className="muted">{skills.length} skills</span></div><div className="mini-library">{skills.slice(0, 5).map((skill) => <button key={skill.id} onClick={() => openSkill(skill.id)}><span className={`category-icon ${categoryClass(skill.category)}`}><BookOpen size={15} /></span><span><strong>{skill.name}</strong><small>{skill.category}</small></span><span className="mini-version">v{skill.version}</span></button>)}</div>{!skills.length && <p className="muted">Publish a skill to make it available to your agent.</p>}<p className="fine-print">Published changes are available on the next load. Drafts stay out of runtime.</p></div>
        <div className="how-it-works"><span className="tiny-label">A SMALLER, SMARTER CONTEXT</span><div><span>01</span><p><strong>Discover</strong>Find relevant skill metadata.</p></div><div><span>02</span><p><strong>Load</strong>Read the current guidance.</p></div><div><span>03</span><p><strong>Apply</strong>Answer with the loaded expertise.</p></div></div>
      </aside>
    </div>
  </>;
}

export function categoryClass(category: string) {
  if (category.toLowerCase().includes("finance")) return "amber";
  if (category.toLowerCase().includes("customer")) return "blue";
  return "sage";
}
