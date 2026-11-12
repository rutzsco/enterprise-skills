import { ArrowRight, ArrowUpRight, BookOpen, Check, Clock3, Plus, Search, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, errorMessage, skillFields } from "./api";
import { categoryClass } from "./Chat";
import { ErrorNotice, Modal, SkillForm, Spinner } from "./components";
import type { Proposal, Skill, SkillFields, SkillHistory, SkillMetadata } from "./types";

const emptySkill: SkillFields = { name: "", description: "", category: "General", guidance: "" };

export function SkillsPage({ skills, selectedId, clearSelection, refresh, notify }: {
  skills: SkillMetadata[]; selectedId: string | null; clearSelection: () => void;
  refresh: () => Promise<void>; notify: (message: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [editing, setEditing] = useState<string | null>(selectedId);
  useEffect(() => { if (selectedId) setEditing(selectedId); }, [selectedId]);
  const visible = skills.filter((skill) => (!category || skill.category === category) && `${skill.name} ${skill.description} ${skill.category}`.toLowerCase().includes(query.toLowerCase()));
  return <>
    <div className="page-heading"><div><h1>Your team's reusable expertise.</h1><p>Practical guidance that agents can discover, load, and apply.</p></div><button className="button primary" onClick={() => setEditing("new")}><Plus size={17} />Create skill</button></div>
    <div className="library-summary"><div><span className="summary-icon"><BookOpen size={22} /></span><span><strong>{skills.length} published skills</strong><small>One shared source for the library, chat, and runtime API.</small></span></div><span className="pill green"><Check size={12} />Available at runtime</span></div>
    <div className="filter-bar"><label className="search-field"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search skills..." aria-label="Search skills" /></label><select aria-label="Filter by category" value={category} onChange={(event) => setCategory(event.target.value)}><option value="">All categories</option>{[...new Set(skills.map((skill) => skill.category))].map((item) => <option key={item}>{item}</option>)}</select><span className="result-count">{visible.length} {visible.length === 1 ? "skill" : "skills"}</span></div>
    <div className="skill-grid">{visible.map((skill) => <button className="skill-card" key={skill.id} onClick={() => setEditing(skill.id)}>
      <div className="skill-card-top"><span className={`category-icon large ${categoryClass(skill.category)}`}><BookOpen size={22} strokeWidth={1.7} /></span><span className="version-pill">v{skill.version}</span></div>
      <span className={`category-label ${categoryClass(skill.category)}`}>{skill.category}</span><h2>{skill.name}</h2><p>{skill.description}</p>
      <div className="skill-card-bottom"><span><Clock3 size={13} />{new Date(skill.updated_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</span><span>View skill <ArrowUpRight size={15} /></span></div>
    </button>)}</div>
    {!visible.length && <div className="empty-panel"><BookOpen size={30} /><h3>{skills.length ? "No skills match that search." : "Your library starts here."}</h3><p>{skills.length ? "Try a different name, category, or keyword." : "Create a skill or turn expert notes into a reviewed proposal."}</p></div>}
    <div className="library-tip"><span><Plus size={18} /></span><div><strong>Review first. Publish deliberately.</strong><p>Saved edits become review drafts. Approved releases reach agents on their next load; older releases remain available for review and rollback.</p></div><ArrowRight size={20} /></div>
    {editing && <SkillEditor key={editing} id={editing} onClose={() => { setEditing(null); clearSelection(); }} onChanged={async (message) => { await refresh(); notify(message); setEditing(null); clearSelection(); }} />}
  </>;
}

function SkillEditor({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: (message: string) => Promise<void> }) {
  const [skill, setSkill] = useState<Skill | null>(null);
  const [value, setValue] = useState<SkillFields>(emptySkill);
  const [loading, setLoading] = useState(id !== "new");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [history, setHistory] = useState<SkillHistory | null>(null);

  useEffect(() => {
    if (id === "new") return;
    let active = true;
    Promise.all([api<Skill>(`/api/skills/${encodeURIComponent(id)}`), api<SkillHistory>(`/api/skills/${encodeURIComponent(id)}/history`)]).then(([current, releases]) => {
      if (active) { setSkill(current); setValue(skillFields(current)); setHistory(releases); }
    }).catch((failure) => { if (active) setError(errorMessage(failure)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id]);

  async function save() {
    setBusy(true); setError("");
    try {
      const saved = skill
        ? await api<Proposal>(`/api/skills/${encodeURIComponent(skill.id)}`, "PUT", { ...value, expected_version: skill.version })
        : await api<Proposal>("/api/skills", "POST", value);
      await onChanged(`${saved.name} is a draft. Open Expert intake > Review queue to approve it.`);
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }

  async function remove() {
    if (!skill) return;
    setBusy(true); setError("");
    try {
      await api(`/api/skills/${encodeURIComponent(skill.id)}?expected_version=${skill.version}`, "DELETE");
      await onChanged("Retirement proposed. Review and approve it in Expert intake. Published guidance is unchanged.");
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }

  async function rollback(version: number) {
    if (!skill) return;
    setBusy(true); setError("");
    try {
      await api(`/api/skills/${encodeURIComponent(skill.id)}/actions`, "POST", {
        action: "rollback", target_version: version, expected_version: skill.version,
        reason: `Restore previously approved guidance from release v${version}.`,
      });
      await onChanged("Rollback proposed. Review its diff and approve in Expert intake.");
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }

  return <Modal title={skill ? "Edit published skill" : "Create a skill"} subtitle={skill ? `${skill.name} / version ${skill.version}` : "Give your agent a focused piece of expertise."} wide onClose={onClose} busy={busy}>
    {loading ? <div className="modal-body"><Spinner label="Loading current guidance..." /></div> : <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
      <div className="modal-body">
        {error && <ErrorNotice message={error} />}
        {(skill || id === "new") && <>
          <div className="notice info"><BookOpen size={17} /><span>Saving creates a draft for explicit approval in Expert intake. Runtime guidance does not change until approval.</span></div>
          <SkillForm value={value} onChange={setValue} disabled={busy} preview={preview} setPreview={setPreview} />
          {skill && <div className="stable-id"><span>Stable skill ID</span><code>{skill.id}</code></div>}
          {history && <details className="published-comparison"><summary>Release history and rollback</summary>
            {history.releases.map((release) => <div key={release.version} className="notice info"><span><strong>v{release.version}</strong> / {release.origin} / {release.reviewer_label}<br /><code>{release.digest}</code></span>
              {release.approved && release.version !== skill?.version && <button className="button secondary" type="button" disabled={busy} onClick={() => void rollback(release.version)}>Propose rollback</button>}
            </div>)}
            {history.events.map((event) => <p key={event.id} className="fine-print">{event.at} / {event.action} {event.version ? `v${event.version}` : ""} / {event.reviewer_label ?? "System"}</p>)}
            <p className="fine-print">Reviewer labels are unverified. This private demo has no end-user sign-in.</p>
            {skill && <a className="button secondary" href={`/api/skills/${encodeURIComponent(skill.id)}/package`}>Download portable package</a>}
          </details>}
          {confirmDelete && <div className="delete-confirm"><strong>Propose retiring this skill?</strong><p>Only approval removes it from discovery. Releases and evidence remain preserved.</p><div><button type="button" className="button danger" disabled={busy} onClick={() => void remove()}>Propose retirement</button><button type="button" className="button secondary" disabled={busy} onClick={() => setConfirmDelete(false)}>Keep skill</button></div></div>}
        </>}
      </div>
      <footer className="modal-footer">{skill ? <button className="text-button danger-text" type="button" disabled={busy} onClick={() => setConfirmDelete(true)}><Trash2 size={16} />Retire skill</button> : <span className="fine-print">Draft only until explicit review.</span>}<div><button className="button secondary" type="button" disabled={busy} onClick={onClose}>Cancel</button><button className="button primary" type="submit" disabled={busy || (id !== "new" && !skill)}>{busy ? <Spinner label="Saving..." /> : <><Check size={16} />Save review draft</>}</button></div></footer>
    </form>}
  </Modal>;
}
