export interface SkillFields {
  name: string;
  description: string;
  category: string;
  guidance: string;
}

export interface SkillMetadata extends Omit<SkillFields, "guidance"> {
  id: string;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface Skill extends SkillMetadata {
  guidance: string;
}

export interface ServiceStatus {
  configured: boolean;
  provider: string;
  framework: string;
  connection: "not_configured" | "not_tested" | "verified" | "failed";
  problems: string[];
  model_deployment: string | null;
  published_skills: number;
  pending_proposals: number;
}

export interface ToolEvent {
  id: string;
  tool: string;
  status: "success" | "error";
  arguments: Record<string, unknown>;
  summary: string;
  duration_ms: number;
  skill?: SkillMetadata;
}

export interface ChatReply {
  session_id: string;
  answer: string;
  events: ToolEvent[];
  loaded_skills: SkillMetadata[];
}

export interface IntakeSummary {
  id: string;
  title: string;
  status: "saved" | "organizing" | "ready" | "failed";
  error: string | null;
  created_at: string;
  updated_at: string;
  pending_count: number;
}

export interface Proposal extends SkillFields {
  id: string;
  intake_id: string;
  action: "create" | "update";
  skill_id: string | null;
  base_version: number | null;
  rationale: string;
  evidence: string[];
  missing_information: string[];
  status: "pending" | "approved" | "rejected";
  revision: number;
  conflict: string | null;
  published_skill_id: string | null;
}

export interface Intake extends Omit<IntakeSummary, "pending_count"> {
  notes: string;
  events: ToolEvent[];
  proposals: Proposal[];
}

export type Page = "chat" | "skills" | "intake" | "runtime";
