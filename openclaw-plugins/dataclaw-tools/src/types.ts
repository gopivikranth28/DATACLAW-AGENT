export type JsonSchema = Record<string, unknown>;

export type DataclawToolDefinition = {
  name: string;
  description: string;
  parameters: JsonSchema;
};

export type DataclawToolsConfig = {
  baseUrl: string;
  token?: string;
  optional: boolean;
  prefix: string;
};

export type DataclawToolCallResponse = {
  ok: boolean;
  result?: unknown;
  detail?: unknown;
  error?: unknown;
};
