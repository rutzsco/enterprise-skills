import { BookOpen, Braces, ChevronRight, CircleHelp, Layers3, MessageSquare, NotebookPen, PanelLeftClose, RefreshCw, ShieldCheck, Sparkles } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "./api";
import { ConnectionBadge, ErrorNotice, SetupDialog, Spinner } from "./components";
import { ChatPage } from "./Chat";
import { SkillsPage } from "./Skills";
import { IntakePage } from "./Intake";
import { RuntimePage } from "./Runtime";
import type { IntakeSummary, Page, Proposal, ServiceStatus, SkillMetadata } from "./types";

const navigation = [
  { id: "chat", label: "Demo chat", icon: MessageSquare },
  { id: "skills", label: "Skill library", icon: BookOpen },
  { id: "intake", label: "Expert intake", icon: NotebookPen },
  { id: "runtime", label: "Runtime API", icon: Braces },
] as const;

export default function App() {
  const [page, setPage] = useState<Page>("chat");
  const [status, setStatus] = useState<ServiceStatus | null>(null);
  const [skills, setSkills] = useState<SkillMetadata[]>([]);
  const [intakes, setIntakes] = useState<IntakeSummary[]>([]);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [error, setError] = useState("");
  const [setupOpen, setSetupOpen] = useState(false);
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null);
  const [notice, setNotice] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [nextStatus, library, notes, queue] = await Promise.all([
        api<ServiceStatus>("/api/status"),
        api<{ skills: SkillMetadata[] }>("/api/skills"),
        api<{ intakes: IntakeSummary[] }>("/api/intakes"),
        api<{ proposals: Proposal[] }>("/api/proposals"),
      ]);
      setStatus(nextStatus);
      setSkills(library.skills);
      setIntakes(notes.intakes);
      setProposals(queue.proposals);
      setError("");
    } catch (failure) {
      setError(errorMessage(failure));
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => { window.scrollTo({ top: 0, behavior: "auto" }); }, [page]);
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 6000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  function openSkill(id: string) {
    setSelectedSkill(id);
    setPage("skills");
  }

  const pending = proposals.filter((proposal) => proposal.status === "pending").length;
  return <div className="app-shell">
    <aside className="sidebar">
      <button className="brand" onClick={() => setPage("chat")} aria-label="Enterprise Memory home">
        <span className="brand-mark"><Layers3 size={24} strokeWidth={1.7} /></span>
        <span>enterprise<span className="brand-second">memory<span className="brand-dot">.</span></span></span>
      </button>
      <div className="workspace-label"><span className="workspace-avatar">EM</span><div>Demo workspace<small>{status?.storage_backend === "azure" ? "Private Azure / trusted access" : "Local, single-user"}</small></div><PanelLeftClose size={14} /></div>
      <p className="nav-heading">WORKSPACE</p>
      <nav aria-label="Workspace navigation">{navigation.map(({ id, label, icon: Icon }) => <button key={id} className={`nav-item ${page === id ? "active" : ""}`} aria-current={page === id ? "page" : undefined} onClick={() => setPage(id)}>
        <Icon size={18} /><span>{label}</span>
        {id === "skills" && status && <span className="nav-count">{status.published_skills}</span>}
        {id === "intake" && pending > 0 && <span className="nav-count">{pending}</span>}
      </button>)}</nav>
      <div className="sidebar-note"><span className="tiny-label">THE IDEA</span><Sparkles size={22} /><h3>Knowledge that<br />gets to work.</h3><p>Capture what experts know.<br />Give agents the right context,<br />right when they need it.</p><div className="mini-flow"><NotebookPen size={15} /><span /><BookOpen size={15} /><span /><MessageSquare size={15} /></div></div>
      <div className="sidebar-bottom"><span className="local-dot" />Hackathon prototype<span className="version">v0.1</span></div>
    </aside>

    <main className="workspace">
      <header className="topbar">
        <div className="breadcrumb"><span>Workspace</span><ChevronRight size={14} /><strong>{navigation.find((item) => item.id === page)?.label}</strong></div>
        <div className="topbar-actions"><span className="synthetic-tag"><ShieldCheck size={14} />Synthetic demo data</span><button className="icon-button" aria-label="Refresh workspace" onClick={() => void refresh()}><RefreshCw size={16} /></button><button className="icon-button" aria-label="Azure setup help" onClick={() => setSetupOpen(true)}><CircleHelp size={18} /></button><span className="user-avatar">YOU</span></div>
      </header>
      <div className="page-content">
        {error && <div className="global-error"><ErrorNotice message={error} /><button className="button secondary" onClick={() => void refresh()}>Retry</button></div>}
        {!status && !error && <div className="loading-page"><Spinner label="Opening your local workspace..." /></div>}
        {status && <>
          <div className="page-eyebrow"><span>ENTERPRISE MEMORY</span><ConnectionBadge status={status} onClick={() => setSetupOpen(true)} /></div>
          <section hidden={page !== "chat"}><ChatPage status={status} skills={skills} onSetup={() => setSetupOpen(true)} openSkill={openSkill} refresh={refresh} /></section>
          {page === "skills" && <SkillsPage skills={skills} selectedId={selectedSkill} clearSelection={() => setSelectedSkill(null)} refresh={refresh} notify={setNotice} />}
          <section hidden={page !== "intake"}><IntakePage status={status} intakes={intakes} proposals={proposals} refresh={refresh} notify={setNotice} onSetup={() => setSetupOpen(true)} /></section>
          {page === "runtime" && <RuntimePage skills={skills} />}
        </>}
      </div>
      <footer className="workspace-footer"><span>Expert knowledge. Discoverable. Loadable. Reviewable.</span><span>{status?.storage_backend === "azure" ? "Private Blob + Cosmos DB" : "Local SQLite"} <span className="footer-dot" /> Azure-powered agents</span></footer>
    </main>
    {notice && <div className="toast" role="status"><ShieldCheck size={17} />{notice}<button className="icon-button" aria-label="Dismiss notification" onClick={() => setNotice("")}>x</button></div>}
    {setupOpen && status && <SetupDialog status={status} onClose={() => setSetupOpen(false)} refresh={refresh} />}
  </div>;
}
