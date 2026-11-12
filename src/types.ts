export interface SkillFields {
  name: string;
  description: string;
  category: string;
  guidance: string;
  owner?: string;
  applicability?: string;
  references?: Record<string, string>;
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
  storage_backend: "sqlite" | "azure";
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
  action: "create" | "update" | "retire" | "rollback";
  skill_id: string | null;
  base_version: number | null;
  rationale: string;
  evidence: string[];
  missing_information: string[];
  status: "pending" | "approved" | "rejected";
  revision: number;
  conflict: string | null;
  published_skill_id: string | null;
  published_version?: number;
  target_version?: number;
  rules?: { rule: string; quotes: string[] }[];
}

export interface SkillHistory {
  active: SkillMetadata & { retired: boolean };
  releases: (SkillMetadata & { approved: boolean; origin: string; digest: string; reviewer_label: string })[];
  events: { id: string; at: string; action: string; version?: number; reviewer_label?: string }[];
}

export interface Intake extends Omit<IntakeSummary, "pending_count"> {
  notes: string;
  events: ToolEvent[];
  proposals: Proposal[];
}

export type Page = "chat" | "skills" | "intake" | "runtime";
