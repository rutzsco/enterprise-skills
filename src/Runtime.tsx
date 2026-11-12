import { ArrowDownToLine, ArrowRight, BookOpen, Braces, Check, Copy, Play, Search } from "lucide-react";
import { useState } from "react";
import { errorMessage } from "./api";
import { ErrorNotice, Spinner } from "./components";
import type { SkillMetadata } from "./types";

export function RuntimePage({ skills }: { skills: SkillMetadata[] }) {
  const [mode, setMode] = useState<"discover" | "load">("discover");
  const [query, setQuery] = useState("");
  const [skillId, setSkillId] = useState(skills[0]?.id ?? "");
  const [result, setResult] = useState<{ status: number; body: unknown; path: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const path = mode === "discover" ? `/api/runtime/skills?query=${encodeURIComponent(query)}` : `/api/runtime/skills/${encodeURIComponent(skillId)}`;
  const example = `curl.exe "${window.location.origin}${path}"`;

  async function run() {
    setBusy(true); setError(""); setResult(null);
    try {
      const response = await fetch(path);
      const body: unknown = await response.json();
      setResult({ status: response.status, body, path });
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }

  async function copy() {
    try { await navigator.clipboard.writeText(example); setCopied(true); window.setTimeout(() => setCopied(false), 2500); }
    catch { setError("Clipboard access was denied. Select and copy the command manually."); }
  }

  return <>
    <div className="page-heading"><div><h1>One library. Any agent.</h1><p>Read-only MCP resources and HTTP endpoints for approved expertise.</p></div><a className="button secondary" href="/api/docs" target="_blank" rel="noreferrer"><Braces size={16} />API reference <ArrowRight size={15} /></a></div>
    <div className="notice info"><Braces size={18} /><span><strong>MCP / Streamable HTTP</strong><br /><code>{window.location.origin}/mcp</code><br />Read <code>skill://index.json</code>, then <code>skill://&#123;id&#125;/SKILL.md</code>. Historical reads explicitly include <code>versions/&#123;version&#125;</code>. No publishing tools are exposed.</span></div>
    <div className="runtime-hero"><div><span className="tiny-label">PROGRESSIVE CONTEXT, NOT PROMPT BLOAT</span><h2>Discover light.<br />Load only what matters.</h2><p>The same published skills power this demo and your own agents.<br />No vector database. No reindexing. No restart after edits.</p></div><div className="runtime-flow" aria-label="Agent discovers metadata, then loads guidance"><span><Braces size={25} /><strong>Your agent</strong></span><ArrowRight size={20} /><span><Search size={25} /><strong>Metadata</strong></span><ArrowRight size={20} /><span><BookOpen size={25} /><strong>Guidance</strong></span></div></div>
    <div className="endpoint-grid"><button className={`endpoint-card ${mode === "discover" ? "selected" : ""}`} onClick={() => { setMode("discover"); setResult(null); }}><span className="endpoint-icon"><Search size={21} /></span><div><span className="tiny-label">01 / DISCOVER</span><h3>Find relevant expertise</h3><p>Names, descriptions, categories, IDs, and versions. Never the full guidance.</p><code><span>GET</span> /api/runtime/skills</code></div></button><button className={`endpoint-card ${mode === "load" ? "selected" : ""}`} onClick={() => { setMode("load"); setResult(null); }}><span className="endpoint-icon"><ArrowDownToLine size={21} /></span><div><span className="tiny-label">02 / LOAD</span><h3>Read the current skill</h3><p>Load Markdown guidance by stable ID. The response includes its exact published version.</p><code><span>GET</span> /api/runtime/skills/&#123;id&#125;</code></div></button></div>
    <div className="api-playground"><div className="panel-title"><span><Braces size={17} />Try the runtime API</span><span className="pill green">Live local requests</span></div>
      <div className="playground-controls">{mode === "discover" ? <label>Search metadata<input value={query} maxLength={200} placeholder="Try software, incident, or leave empty" onChange={(event) => { setQuery(event.target.value); setResult(null); }} /></label> : <label>Published skill<select value={skillId} onChange={(event) => { setSkillId(event.target.value); setResult(null); }}>{!skills.length && <option value="">No published skills</option>}{skills.map((skill) => <option key={skill.id} value={skill.id}>{skill.name} / v{skill.version}</option>)}</select></label>}<button className="button primary" disabled={busy || (mode === "load" && !skillId)} onClick={() => void run()}>{busy ? <Spinner label="Requesting..." /> : <><Play size={15} />Send request</>}</button></div>
      <div className="request-code"><pre>{example}</pre><button aria-label="Copy request command" className="icon-button" onClick={() => void copy()}>{copied ? <Check size={16} /> : <Copy size={16} />}</button></div>
      {error && <div className="playground-error"><ErrorNotice message={error} /></div>}
      <div className="response-heading"><span>RESPONSE BODY</span>{result && <span className={`pill ${result.status < 400 ? "green" : "red"}`}>HTTP {result.status}</span>}</div>
      {result ? <><pre className="response-code">{JSON.stringify(result.body, null, 2)}</pre><div className="response-source">Actual response from <code>{result.path}</code></div></> : <div className="response-empty"><Braces size={24} /><span>Send a request to inspect the actual published data.</span><small>There are no canned responses in this explorer.</small></div>}
    </div>
    <div className="runtime-rules"><div><Check size={17} /><span><strong>Current by design</strong>Responses are not cached. Reload when you need the latest version.</span></div><div><Check size={17} /><span><strong>Published means published</strong>Pending and rejected proposals never appear in these endpoints.</span></div><div><Check size={17} /><span><strong>Trusted demo boundary</strong>No end-user sign-in or skill ACLs. Use loopback locally or approved private Azure access only.</span></div></div>
  </>;
}
