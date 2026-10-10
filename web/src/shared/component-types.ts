export interface SchemaRequirement {
  role: string;
  dtype: "datetime" | "numeric" | "string" | "any";
  min: number;
}

export interface ComponentManifest {
  id: string;
  name: string;
  description: string;
  tags: string[];
  contract_version: 1;
  schema: { requires: SchemaRequirement[] };
  origin: "builtin" | "generated" | "imported";
  created_at: string;
}

/** `session_id` and `dataset` are both set or both null; the server refuses half a binding. */
export interface SaveComponentRequest {
  id: string;
  name: string;
  description: string;
  tags: string[];
  source: string;
  session_id: string | null;
  dataset: string | null;
}

export interface ToCodeResponse {
  code: string;
}
