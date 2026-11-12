import { AlertCircle, ArrowRight, BookOpen, Check, ChevronRight, ClipboardList, FileText, GitPullRequestArrow, NotebookPen, Save, Sparkles, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, errorMessage, skillFields } from "./api";
import { ErrorNotice, MarkdownText, Modal, SkillForm, Spinner, ToolTrace } from "./components";
import type { Intake, IntakeSummary, Proposal, ServiceStatus, Skill, SkillFields } from "./types";

const sampleNotes = `Synthetic workshop notes - not a real company policy.

Software purchasing update: Finance approval is now required for every software purchase, even below $2,500 annually. Keep the existing Procurement approval requirement above $10,000. Tools handling personal or confidential data still need a security review.

People keep quoting monthly prices. The request should show the annual committed cost including required fees.

We still need to confirm who in Finance owns the queue and what the turnaround time is. Don't promise an SLA yet.`;

const intakeLabels: Record<IntakeSummary["status"], string> = {
  saved: "Notes saved", organizing: "Organizing", ready: "Review ready", failed: "Needs attention",
};

export function IntakePage({ status, intakes, proposals, refresh, notify, onSetup }: {
  status: ServiceStatus; intakes: IntakeSummary[]; proposals: Proposal[];
  refresh: () => Promise<void>; notify: (message: string) => void; onSetup: () => void;
}) {
  const [tab, setTab] = useState<"capture" | "review">("capture");
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [savedId, setSavedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const [selectedIntake, setSelectedIntake] = useState<string | null>(null);
  const [selectedProposal, setSelectedProposal] = useState<string | null>(null);
  const pending = proposals.filter((proposal) => proposal.status === "pending");
  const visibleProposals = showHistory ? proposals : pending;

  async function submit(organize: boolean) {
    setBusy(true); setError("");
    try {
      let id = savedId;
      if (!id) {
        const intake = await api<Intake>("/api/intakes", "POST", { title, notes });
        id = intake.id;
        setSavedId(id);
      }
      if (organize) {
        const result = await api<Intake>(`/api/intakes/${id}/organize`, "POST");
        notify(`${result.proposals.length} proposals are ready for review. Nothing has been published.`);
        setTab("review");
        setTitle(""); setNotes(""); setSavedId(null);
      } else {
        notify("Expert notes saved locally. No skills were changed.");
      }
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); await refresh(); }
  }

  async function organizeSaved(id: string) {
    setBusy(true); setError("");
    try {
      const result = await api<Intake>(`/api/intakes/${id}/organize`, "POST");
      setSelectedIntake(null); setTab("review");
      notify(`${result.proposals.length} draft proposals are ready. Review them before publication.`);
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); await refresh(); }
  }

  return <>
    <div className="page-heading"><div><h1>Turn know-how into shared knowledge.</h1><p>Bring the rough notes. Let an agent organize them. Keep people in control.</p></div><span className="pill neutral"><GitPullRequestArrow size={14} />Review before publish</span></div>
    <div className="intake-tabs" role="tablist" aria-label="Expert intake views"><button role="tab" aria-selected={tab === "capture"} className={tab === "capture" ? "selected" : ""} onClick={() => setTab("capture")}><NotebookPen size={16} />Capture expertise</button><button role="tab" aria-selected={tab === "review"} className={tab === "review" ? "selected" : ""} onClick={() => setTab("review")}><ClipboardList size={16} />Review queue<span className="number-pill">{pending.length}</span></button></div>
    {error && <ErrorNotice message={error} />}
    {tab === "capture" ? <>
      <div className="intake-layout">
        <form className="capture-card" onSubmit={(event) => { event.preventDefault(); void submit(false); }}>
          <div className="card-title"><div><h2>What does your expert know?</h2><p>Decision rules, exceptions, hard-earned lessons. Messy is fine.</p></div><NotebookPen size={23} /></div>
          <label>Notes title<input required minLength={2} maxLength={100} disabled={busy} value={title} onChange={(event) => { setTitle(event.target.value); setSavedId(null); }} placeholder="e.g. Notes from the Finance workshop" /></label>
          <label>Expert notes<textarea required minLength={30} maxLength={16000} rows={13} disabled={busy} value={notes} onChange={(event) => { setNotes(event.target.value); setSavedId(null); }} placeholder={"Paste the rules and context your team relies on.\n\nWhen does this apply?\nWhat should someone do?\nWhat are the thresholds or exceptions?\nWhat is still unknown?"} /></label>
          <div className="notes-helper"><button type="button" className="text-button" disabled={busy} onClick={() => { setTitle("Software purchasing workshop"); setNotes(sampleNotes); setSavedId(null); }}><Sparkles size={14} />Use synthetic example</button><span>{notes.length.toLocaleString()} / 16,000</span></div>
          <div className="capture-actions"><button type="submit" className="button secondary" disabled={busy || title.trim().length < 2 || notes.trim().length < 30}><Save size={16} />{savedId ? "Notes saved" : "Save notes"}</button><button type="button" className="button primary" disabled={busy || !status.configured || title.trim().length < 2 || notes.trim().length < 30} onClick={() => void submit(true)}>{busy ? <Spinner label="Working with Foundry..." /> : <><Sparkles size={16} />Organize with agent</>}</button></div>
          {!status.configured && <div className="inline-setup"><AlertCircle size={15} /><span>Save notes now. Connect Foundry to generate proposals.</span><button type="button" onClick={onSetup}>Set up <ArrowRight size={13} /></button></div>}
          <p className="fine-print">Organization sends these notes to your configured Azure project. Use synthetic data only.</p>
        </form>
        <aside className="authoring-guide"><span className="tiny-label">FROM EXPERIENCE TO EXPERTISE</span><h2>A careful handoff.<br />Not a blind rewrite.</h2><div className="authoring-step"><span>1</span><div><h3>Inspect the library</h3><p>The agent discovers existing skills and loads relevant guidance before proposing updates.</p></div></div><div className="authoring-step"><span>2</span><div><h3>Organize, don't invent</h3><p>New skills or focused updates, grounded in your notes. Missing information stays visible.</p></div></div><div className="authoring-step"><span>3</span><div><h3>You review. You publish.</h3><p>Edit, approve, or reject each draft. Published guidance stays unchanged until approval.</p></div></div><div className="review-lock"><GitPullRequestArrow size={22} /><p>Drafts are never exposed to chat or runtime consumers.</p></div></aside>
      </div>
      <div className="section-heading"><h2>Recent expert notes</h2><span>{intakes.length} saved</span></div>
      {intakes.length ? <div className="notes-list">{intakes.map((intake) => <button key={intake.id} onClick={() => setSelectedIntake(intake.id)}><span className="note-icon"><FileText size={19} /></span><span className="note-description"><strong>{intake.title}</strong><small>{new Date(intake.created_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</small></span><span className={`pill ${intake.status === "ready" ? "green" : intake.status === "failed" ? "red" : "neutral"}`}>{intakeLabels[intake.status]}</span><ChevronRight size={17} /></button>)}</div> : <div className="small-empty"><NotebookPen size={20} /><span>No notes yet. Saved notes survive server restarts.</span></div>}
    </> : <>
      <div className="queue-heading"><p><strong>{pending.length} proposals</strong> awaiting human review</p><label className="checkbox-label"><input type="checkbox" checked={showHistory} onChange={(event) => setShowHistory(event.target.checked)} />Show approved and rejected</label></div>
      {visibleProposals.length ? <div className="proposal-grid">{visibleProposals.map((proposal) => <button key={proposal.id} className="proposal-card" onClick={() => setSelectedProposal(proposal.id)}>
        <div><span className={`pill ${proposal.action === "create" ? "green" : "blue"}`}>{proposal.action === "create" ? "New skill" : `${proposal.action} v${proposal.base_version}`}</span><span className="proposal-status">{proposal.status === "pending" ? "Not published" : proposal.status}</span></div>
        <h2>{proposal.name}</h2><p>{proposal.rationale}</p>
        {proposal.conflict && <span className="conflict-label"><AlertCircle size={14} />Published version changed</span>}
        {!proposal.conflict && proposal.missing_information.length > 0 && <span className="gap-label"><AlertCircle size={14} />{proposal.missing_information.length} information gaps flagged</span>}
        <footer><span>{proposal.evidence.length} source excerpts</span><strong>{proposal.status === "pending" ? "Review proposal" : "View outcome"} <ArrowRight size={15} /></strong></footer>
      </button>)}</div> : <div className="empty-panel review-empty"><span className="empty-round"><ClipboardList size={30} /></span><h2>Expertise deserves a second look.</h2><p>Agent-generated proposals will appear here.<br />Nothing reaches the live library without your approval.</p><button className="button secondary" onClick={() => setTab("capture")}>Capture expert notes <ArrowRight size={15} /></button></div>}
    </>}
    {selectedIntake && <IntakeDetail id={selectedIntake} onClose={() => setSelectedIntake(null)} canOrganize={status.configured && !busy} busy={busy} error={error} organize={organizeSaved} openProposal={(id) => { setSelectedIntake(null); setSelectedProposal(id); }} />}
    {selectedProposal && <ProposalEditor id={selectedProposal} onClose={() => setSelectedProposal(null)} onChanged={async (message, close) => { await refresh(); notify(message); if (close) setSelectedProposal(null); }} />}
  </>;
}

function IntakeDetail({ id, onClose, canOrganize, organize, openProposal, busy, error }: {
  id: string; onClose: () => void; canOrganize: boolean; busy: boolean; error: string;
  organize: (id: string) => Promise<void>; openProposal: (id: string) => void;
}) {
  const [intake, setIntake] = useState<Intake | null>(null);
  const [loadError, setLoadError] = useState("");
  useEffect(() => {
    let active = true;
    api<Intake>(`/api/intakes/${id}`).then((value) => { if (active) setIntake(value); }).catch((failure) => { if (active) setLoadError(errorMessage(failure)); });
    return () => { active = false; };
  }, [id, busy]);
  return <Modal title={intake?.title ?? "Expert notes"} subtitle="Saved source notes and the actual organization trace." onClose={onClose} wide busy={busy}>
    <div className="modal-body">{(loadError || error) && <ErrorNotice message={loadError || error} />}{intake ? <>
      <div className="source-notes">{intake.notes}</div>{intake.error && <ErrorNotice message={intake.error} />}<ToolTrace events={intake.events} />
      {intake.proposals.map((proposal) => <button className="proposal-link" key={proposal.id} onClick={() => openProposal(proposal.id)}><BookOpen size={16} /><span>{proposal.name}</span><span className="pill neutral">{proposal.status}</span><ArrowRight size={15} /></button>)}
    </> : !loadError && <Spinner label="Loading saved notes..." />}</div>
    <footer className="modal-footer"><span className="fine-print">Source notes are retained with every proposal.</span>{intake && ["saved", "failed"].includes(intake.status) && <button className="button primary" disabled={!canOrganize || busy} onClick={() => void organize(id)}>{busy ? <Spinner label="Organizing..." /> : <><Sparkles size={15} />Organize with agent</>}</button>}</footer>
  </Modal>;
}

function ProposalEditor({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: (message: string, close: boolean) => Promise<void> }) {
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [current, setCurrent] = useState<Skill | null>(null);
  const [value, setValue] = useState<SkillFields | null>(null);
  const [gaps, setGaps] = useState("");
  const [preview, setPreview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [diff, setDiff] = useState("");

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const result = await api<Proposal>(`/api/proposals/${id}`);
        if (!active) return;
        setProposal(result); setValue(skillFields(result)); setGaps(result.missing_information.join("\n"));
        if (result.status === "pending") {
          const change = await api<{ diff: string }>(`/api/proposals/${id}/diff`);
          if (active) setDiff(change.diff);
        }
        if (result.skill_id && result.status === "pending") {
          const target = await api<Skill>(`/api/skills/${encodeURIComponent(result.skill_id)}`);
          if (active) setCurrent(target);
        }
      } catch (failure) { if (active) setError(errorMessage(failure)); }
      finally { if (active) setLoading(false); }
    }
    void load();
    return () => { active = false; };
  }, [id]);

  const dirty = proposal && value && (JSON.stringify(value) !== JSON.stringify(skillFields(proposal)) || gaps.trim() !== proposal.missing_information.join("\n"));
  const closed = proposal?.status !== "pending";
  const releaseAction = proposal?.action === "rollback" || proposal?.action === "retire";

  async function saveDraft() {
    if (!proposal || !value) return;
    setBusy(true); setError("");
    try {
      const updated = await api<Proposal>(`/api/proposals/${id}`, "PUT", { ...value, expected_revision: proposal.revision, missing_information: gaps.split("\n").map((item) => item.trim()).filter(Boolean) });
      setProposal(updated); setValue(skillFields(updated)); setGaps(updated.missing_information.join("\n"));
      setDiff((await api<{ diff: string }>(`/api/proposals/${id}/diff`)).diff);
      await onChanged("Draft saved. The published library is unchanged.", false);
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }

  async function review(action: "approve" | "reject") {
    if (!proposal) return;
    setBusy(true); setError("");
    try {
      await api(`/api/proposals/${id}/${action}`, "POST", { expected_revision: proposal.revision });
      await onChanged(action === "approve" ? "Proposal approved and published. The new guidance is available on the next runtime load." : "Proposal rejected. Published skills were not changed.", true);
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }

  return <Modal title="Review a skill proposal" subtitle={proposal ? `${proposal.action === "create" ? "New skill" : `Update from v${proposal.base_version}`} / draft revision ${proposal.revision}` : "Loading proposal..."} onClose={onClose} wide busy={busy}>
    <form onSubmit={(event) => { event.preventDefault(); void saveDraft(); }}>
      <div className="modal-body">
        {error && <ErrorNotice message={error} />}
        {loading ? <Spinner label="Loading the proposal and published version..." /> : proposal && value && <>
          <div className={`notice ${closed ? "info" : "review-notice"}`}><GitPullRequestArrow size={19} /><span>{closed ? `This proposal was ${proposal.status}. Its original source evidence is retained below.` : "This is an agent-authored draft, not live policy. Verify every rule and resolve gaps before approving."}</span></div>
          {proposal.conflict && <ErrorNotice message={proposal.conflict} />}
          <div className="proposal-rationale"><span className="tiny-label">WHY THIS CHANGE</span><p>{proposal.rationale}</p></div>
          <details className="evidence" open><summary>Evidence from the expert notes <span>{proposal.evidence.length} excerpts</span></summary>{proposal.evidence.map((quote, index) => <blockquote key={index}>{quote}</blockquote>)}</details>
          {proposal.rules?.map((rule, index) => <details className="evidence" key={index}><summary>Rule {index + 1}: {rule.rule}</summary>{rule.quotes.map((quote, quoteIndex) => <blockquote key={quoteIndex}>{quote}</blockquote>)}</details>)}
          {!closed && <details className="published-comparison" open><summary>Exact guidance diff {proposal.target_version ? `(target v${proposal.target_version})` : ""}</summary><pre className="response-code">{diff || "No instruction text changes."}</pre></details>}
          {current && <details className="published-comparison"><summary>Compare with published guidance <span>Current v{current.version}</span></summary><MarkdownText>{current.guidance}</MarkdownText></details>}
          {!releaseAction && <SkillForm value={value} onChange={setValue} disabled={busy || closed} preview={preview} setPreview={setPreview} />}
          {!releaseAction && <label className="gaps-field">Missing information <span className="field-help">One unanswered question per line. Do not invent a policy to fill a gap.</span><textarea rows={3} value={gaps} disabled={busy || closed} onChange={(event) => setGaps(event.target.value)} placeholder="No gaps flagged by the agent. Review the source carefully." /></label>}
          {dirty && !closed && <p className="unsaved-note"><AlertCircle size={14} />Save your draft edits before approving.</p>}
        </>}
      </div>
      <footer className="modal-footer">{proposal && !closed ? <><button type="button" className="text-button danger-text" disabled={busy} onClick={() => void review("reject")}><X size={15} />Reject draft</button><div><button type="submit" className="button secondary" disabled={busy || !dirty}><Save size={15} />Save draft</button><button type="button" className="button primary" disabled={busy || !!dirty || !!proposal.conflict} onClick={() => void review("approve")}>{busy ? <Spinner label="Saving..." /> : <><Check size={16} />Approve &amp; publish</>}</button></div></> : <><span className="fine-print">Only approved proposals enter the runtime catalog.</span><button type="button" className="button secondary" onClick={onClose}>Close</button></>}</footer>
    </form>
  </Modal>;
}
