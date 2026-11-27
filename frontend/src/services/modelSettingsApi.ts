import { apiClient } from './apiClient';

export type ModelProvider = 'ollama' | 'openai' | 'vllm';

export interface LlmValues {
  provider: ModelProvider;
  model: string;
  temperature: number;
  max_tokens: number;
  context_window: number;
  base_url: string | null;
}

export interface EmbeddingValues {
  provider: ModelProvider;
  model: string;
  base_url: string | null;
}

export interface ModelSection<T> {
  /** What is actually used: tenant overrides on top of the server defaults. */
  effective: T;
  /** Server defaults: what an empty field falls back to. */
  defaults: Omit<T, 'base_url'>;
  /** Only the values this tenant has set. */
  overrides: Partial<T>;
  has_api_key: boolean;
  /** False when the stored key can't be decrypted (the server's encryption key changed):
   *  it has to be entered again. Missing from older servers. */
  api_key_readable?: boolean;
}

export interface ModelSettings {
  can_edit: boolean;
  /** Base URLs the server lets tenants choose; empty = only the server's own endpoints. */
  allowed_base_urls: string[];
  llm: ModelSection<LlmValues>;
  embedding: ModelSection<EmbeddingValues> & {
    /** The embedding model can't change while the workspace has indexed documents. */
    locked: boolean;
    /** Vector size the search index expects. */
    dimension: number;
  };
}

/** Overrides to store (omitted/null = server default). api_key: omit to keep the stored
 *  key, null to remove it, a string to set it. */
export type LlmUpdate = Partial<Omit<LlmValues, 'base_url'>> & { base_url?: string | null; api_key?: string | null };
export type EmbeddingUpdate = Partial<Omit<EmbeddingValues, 'base_url'>> & {
  base_url?: string | null;
  api_key?: string | null;
};

export const getModelSettings = async (tenantId: string): Promise<ModelSettings> => {
  const res = await apiClient.get<ModelSettings>(`/api/v1/tenants/${tenantId}/model-settings`);
  return res.data;
};

export const updateModelSettings = async (
  tenantId: string,
  body: { llm?: LlmUpdate; embedding?: EmbeddingUpdate },
): Promise<ModelSettings> => {
  const res = await apiClient.put<ModelSettings>(`/api/v1/tenants/${tenantId}/model-settings`, body);
  return res.data;
};
