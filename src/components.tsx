import { AlertCircle, ArrowRight, Check, ChevronDown, CircleDot, Code2, FileText, LoaderCircle, Search, Settings2, X } from "lucide-react";
import { useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";
import Markdown from "react-markdown";
import type { ServiceStatus, SkillFields, ToolEvent } from "./types";

export function MarkdownText({ children }: { children: string }) {
  return <div className="markdown"><Markdown skipHtml disallowedElements={["img"]} components={{
    a: ({ children: text, href, title }) => <a href={href} title={title} target="_blank" rel="noreferrer noopener">{text}</a>,
  }}>{children}</Markdown></div>;
}

export function ErrorNotice({ message }: { message: string }) {
  return <div className="notice error" role="alert"><AlertCircle size={18} /><span>{message}</span></div>;
}

export function Spinner({ label = "Working..." }: { label?: string }) {
  return <span className="working" role="status"><LoaderCircle className="spin" size={17} />{label}</span>;
}

export function Modal({ title, subtitle, children, onClose, wide = false, busy = false }: {
  title: string; subtitle?: string; children: ReactNode; onClose: () => void; wide?: boolean; busy?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  return <dialog ref={dialog} aria-labelledby={titleId} className={`modal ${wide ? "wide" : ""}`} onCancel={(event) => {
    event.preventDefault();
    if (!busy) onClose();
  }}>
    <header className="modal-header">
      <div><h2 id={titleId}>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>
      <button className="icon-button" aria-label="Close dialog" disabled={busy} onClick={onClose}><X size={21} /></button>
    </header>
    {children}
  </dialog>;
}

export function ToolTrace({ events }: { events: ToolEvent[] }) {
  if (!events.length) return null;
  return <details className="tool-trace" open>
    <summary><Code2 size={15} /><span>Actual tool activity</span><span className="trace-count">{events.length} calls</span><ChevronDown size={14} /></summary>
    <div className="trace-steps">{events.map((event, index) => <div className={`trace-step ${event.status}`} key={`${event.id}-${index}`}>
      <span className="trace-symbol">{event.status === "error" ? <AlertCircle size={15} /> : event.tool === "discover_skills" ? <Search size={15} /> : <FileText size={15} />}</span>
      <div><code>{event.tool}</code><p>{event.summary}</p><small>{JSON.stringify(event.arguments)}</small></div>
      <span className="trace-time">{event.duration_ms} ms</span>
    </div>)}</div>
  </details>;
}

export function SkillForm({ value, onChange, disabled = false, preview, setPreview }: {
  value: SkillFields;
  onChange: (value: SkillFields) => void;
  disabled?: boolean;
  preview: boolean;
  setPreview: (value: boolean) => void;
}) {
  return <div className="skill-form">
    <div className="field-pair">
      <label>Skill name<input required minLength={2} maxLength={100} disabled={disabled} value={value.name} placeholder="e.g. Incident response" onChange={(event) => onChange({ ...value, name: event.target.value })} /></label>
      <label>Category<input required minLength={2} maxLength={40} disabled={disabled} value={value.category} placeholder="e.g. Operations" onChange={(event) => onChange({ ...value, category: event.target.value })} /></label>
    </div>
    <label>Description<textarea required minLength={8} maxLength={400} rows={2} disabled={disabled} value={value.description} placeholder="When should an agent use this expertise?" onChange={(event) => onChange({ ...value, description: event.target.value })} /><span className="field-help">Used for discovery. Keep the decision rules in the guidance below.</span></label>
    <label>Owner<input minLength={2} maxLength={100} disabled={disabled} value={value.owner ?? "Unassigned"} onChange={(event) => onChange({ ...value, owner: event.target.value })} /></label>
    <label>Applicability<textarea minLength={2} maxLength={500} rows={2} disabled={disabled} value={value.applicability ?? "Review applicability before use."} onChange={(event) => onChange({ ...value, applicability: event.target.value })} /></label>
    <div className="guidance-heading"><label htmlFor="skill-guidance">Markdown guidance</label><div className="segmented small">
      <button type="button" className={!preview ? "selected" : ""} onClick={() => setPreview(false)}>Write</button>
      <button type="button" className={preview ? "selected" : ""} onClick={() => setPreview(true)}>Preview</button>
    </div></div>
    {preview
      ? <div className="guidance-preview"><MarkdownText>{value.guidance || "Your guidance preview will appear here."}</MarkdownText></div>
      : <textarea id="skill-guidance" className="code-input" required minLength={20} maxLength={16000} rows={13} disabled={disabled} value={value.guidance} placeholder={"# When to use this skill\n\n## Decision rules\n- ...\n\n## Missing information\n- ..."} onChange={(event) => onChange({ ...value, guidance: event.target.value })} />}
    <span className="field-help">Knowledge and decision rules only. Skills cannot run code or authorize actions.</span>
  </div>;
}

export function ConnectionBadge({ status, onClick }: { status: ServiceStatus; onClick: () => void }) {
  const verified = status.connection === "verified";
  const label = verified ? "Foundry verified" : status.connection === "failed" ? "Foundry needs attention" : status.configured ? "Foundry configured" : "Connect Foundry";
  return <button className={`connection-badge ${verified ? "connected" : ""}`} onClick={onClick}><CircleDot size={13} />{label}<Settings2 size={13} /></button>;
}

export function SetupDialog({ status, onClose, refresh }: { status: ServiceStatus; onClose: () => void; refresh: () => Promise<void> }) {
  return <Modal title="Connect Azure Foundry" subtitle="Your project. Your model. Credentials stay on the server." onClose={onClose}>
    <div className="modal-body setup-body">
      <div className={`notice ${status.connection === "verified" ? "success" : "info"}`}>
        {status.connection === "verified" ? <Check size={18} /> : <CircleDot size={18} />}
        <span>{status.connection === "verified" ? "A real Foundry run has succeeded in this server session." : status.configured ? "Configuration is present. Access is not verified until a real agent run succeeds." : "Live chat and note organization need Azure configuration. Your local library and saved notes work now."}</span>
      </div>
      <ol className="setup-steps">
        <li><strong>Use an existing Foundry project</strong><p>Deploy a model with function calling. Your Azure identity needs permission to create and run prompt agents in the project.</p></li>
        <li><strong>Copy .env.example to .env</strong><pre>{`FOUNDRY_PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>\nFOUNDRY_MODEL_DEPLOYMENT=<deployment-name>`}</pre></li>
        <li><strong>Sign in and restart the API server</strong><pre>{`az login\npython -m uvicorn server.main:app --host 127.0.0.1 --port 8000`}</pre><p>The server uses DefaultAzureCredential and Microsoft Agent Framework with registered Foundry agents. There is no simulated chat fallback.</p></li>
      </ol>
      {!!status.problems.length && <div className="setup-checks">{status.problems.map((problem) => <p key={problem}><AlertCircle size={15} />{problem}</p>)}</div>}
      <p className="fine-print">Only use synthetic data for this demo. Chat, SME notes, discovered metadata, and loaded guidance are sent to your configured Azure project. There is no end-user authentication: use loopback locally or trusted private Azure access.</p>
    </div>
    <footer className="modal-footer"><a href="https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/function-calling" target="_blank" rel="noreferrer">Official Foundry guide <ArrowRight size={14} /></a><button className="button primary" onClick={() => void refresh()}>Refresh status</button></footer>
  </Modal>;
}
