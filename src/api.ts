import type { ToolEvent } from "./types";

export class ApiError extends Error {
  events: ToolEvent[];
  resetRequired: boolean;

  constructor(message: string, events: ToolEvent[] = [], resetRequired = false) {
    super(message);
    this.events = events;
    this.resetRequired = resetRequired;
  }
}

export async function api<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(
      "The request could not be confirmed. Check that the local server is running and refresh before retrying a change.",
      [],
      path === "/api/chat",
    );
  }
  if (response.status === 204) return undefined as T;
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiError(`The server returned an unreadable response (HTTP ${response.status}). Check the server logs.`, [], path === "/api/chat");
  }
  if (!response.ok) {
    const body = isRecord(data) ? data : {};
    const error = isRecord(body.error) ? body.error : {};
    throw new ApiError(
      typeof error.message === "string" ? error.message : `Request failed (${response.status}).`,
      Array.isArray(body.events) ? body.events.filter(isToolEvent) : [],
      body.reset_required === true,
    );
  }
  return data as T;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isToolEvent(value: unknown): value is ToolEvent {
  return isRecord(value) && typeof value.id === "string" && typeof value.tool === "string"
    && (value.status === "success" || value.status === "error") && isRecord(value.arguments)
    && typeof value.summary === "string" && typeof value.duration_ms === "number";
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The operation failed. Please try again.";
}

export function skillFields(value: import("./types").SkillFields) {
  return { name: value.name, description: value.description, category: value.category, guidance: value.guidance,
    owner: value.owner ?? "Unassigned", applicability: value.applicability ?? "Review applicability before use.",
    references: value.references ?? {} };
}
