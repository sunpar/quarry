import type {
  DatasetMeta,
  QueryResult,
  QuerySpec,
  ReplayReport,
  Session,
  SessionMeta,
  SessionStatus,
  Step,
  StepRequest,
} from "@/shared/api-types";
import type { JsonObject } from "@/shared/json";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(`${status}: ${detail}`);
  }
}

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

export class ApiClient {
  constructor(
    private readonly token: string,
    private readonly fetchImpl: Fetch = (input, init) => fetch(input, init),
  ) {}

  listSessions(): Promise<SessionMeta[]> {
    return this.request("GET", "/sessions");
  }

  createSession(title: string): Promise<SessionMeta> {
    return this.request("POST", "/sessions", { title });
  }

  getSession(id: string): Promise<Session> {
    return this.request("GET", `/sessions/${id}`);
  }

  getStatus(id: string): Promise<SessionStatus> {
    return this.request("GET", `/sessions/${id}/status`);
  }

  postStep(id: string, body: StepRequest): Promise<Step> {
    return this.request("POST", `/sessions/${id}/steps`, body);
  }

  postManualStep(id: string, code: string): Promise<Step> {
    return this.request("POST", `/sessions/${id}/steps/manual`, { code });
  }

  interrupt(id: string): Promise<{ ok: boolean }> {
    return this.request("POST", `/sessions/${id}/interrupt`);
  }

  query(id: string, spec: QuerySpec): Promise<QueryResult> {
    return this.request("POST", `/sessions/${id}/query`, spec);
  }

  datasets(id: string): Promise<DatasetMeta[]> {
    return this.request("GET", `/sessions/${id}/datasets`);
  }

  restart(id: string): Promise<ReplayReport> {
    return this.request("POST", `/sessions/${id}/restart`);
  }

  postSnapshot(
    id: string,
    stepId: string,
    body: { state: JsonObject; queries: QuerySpec[] },
  ): Promise<{ count: number }> {
    return this.request(
      "POST",
      `/sessions/${id}/steps/${stepId}/snapshots`,
      body,
    );
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<T> {
    const headers = new Headers({ authorization: `Bearer ${this.token}` });
    if (body !== undefined) headers.set("content-type", "application/json");
    const response = await this.fetchImpl(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      const detail = await readDetail(response);
      throw new ApiError(response.status, detail);
    }
    return (await response.json()) as T;
  }
}

async function readDetail(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: unknown };
    return typeof data.detail === "string"
      ? data.detail
      : JSON.stringify(data.detail ?? data);
  } catch {
    return response.statusText;
  }
}
