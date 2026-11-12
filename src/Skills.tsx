import { ArrowRight, ArrowUpRight, BookOpen, Check, Clock3, Plus, Search, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, errorMessage, skillFields } from "./api";
import { categoryClass } from "./Chat";
import { ErrorNotice, Modal, SkillForm, Spinner } from "./components";
import type { Skill, SkillFields, SkillMetadata } from "./types";

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
    <div className="library-tip"><span><Plus size={18} /></span><div><strong>Keep the knowledge. Skip the reindexing.</strong><p>Every saved edit increments the skill version. Agents get the latest published guidance on their next load.</p></div><ArrowRight size={20} /></div>
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

  useEffect(() => {
    if (id === "new") return;
    let active = true;
    api<Skill>(`/api/skills/${encodeURIComponent(id)}`).then((current) => {
      if (active) { setSkill(current); setValue(skillFields(current)); }
    }).catch((failure) => { if (active) setError(errorMessage(failure)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id]);

  async function save() {
    setBusy(true); setError("");
    try {
      const saved = skill
        ? await api<Skill>(`/api/skills/${encodeURIComponent(skill.id)}`, "PUT", { ...value, expected_version: skill.version })
        : await api<Skill>("/api/skills", "POST", value);
      await onChanged(`${saved.name} v${saved.version} is published and available to runtime loads.`);
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }

  async function remove() {
    if (!skill) return;
    setBusy(true); setError("");
    try {
      await api(`/api/skills/${encodeURIComponent(skill.id)}?expected_version=${skill.version}`, "DELETE");
      await onChanged("Skill deleted. Future runtime loads will report it as unavailable.");
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }

  return <Modal title={skill ? "Edit published skill" : "Create a skill"} subtitle={skill ? `${skill.name} / version ${skill.version}` : "Give your agent a focused piece of expertise."} wide onClose={onClose} busy={busy}>
    {loading ? <div className="modal-body"><Spinner label="Loading current guidance..." /></div> : <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
      <div className="modal-body">
        {error && <ErrorNotice message={error} />}
        {(skill || id === "new") && <>
          <div className="notice info"><BookOpen size={17} /><span>Saving here publishes directly. For agent-assisted drafts and approval, use Expert intake.</span></div>
          <SkillForm value={value} onChange={setValue} disabled={busy} preview={preview} setPreview={setPreview} />
          {skill && <div className="stable-id"><span>Stable skill ID</span><code>{skill.id}</code></div>}
          {confirmDelete && <div className="delete-confirm"><strong>Delete this published skill?</strong><p>This removes it from discovery and future loads. Existing conversation text is not erased. Pending update proposals will become stale.</p><div><button type="button" className="button danger" disabled={busy} onClick={() => void remove()}>Delete permanently</button><button type="button" className="button secondary" disabled={busy} onClick={() => setConfirmDelete(false)}>Keep skill</button></div></div>}
        </>}
      </div>
      <footer className="modal-footer">{skill ? <button className="text-button danger-text" type="button" disabled={busy} onClick={() => setConfirmDelete(true)}><Trash2 size={16} />Delete skill</button> : <span className="fine-print">Published immediately on save.</span>}<div><button className="button secondary" type="button" disabled={busy} onClick={onClose}>Cancel</button><button className="button primary" type="submit" disabled={busy || (id !== "new" && !skill)}>{busy ? <Spinner label="Saving..." /> : <><Check size={16} />{skill ? "Publish changes" : "Publish skill"}</>}</button></div></footer>
    </form>}
  </Modal>;
}
