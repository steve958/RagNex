// Shared pieces for the LLM and Embeddings settings forms.
import React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useAuth } from '../../store/auth';
import {
  EmbeddingUpdate,
  getModelSettings,
  LlmUpdate,
  ModelProvider,
  ModelSettings,
  updateModelSettings,
} from '../../services/modelSettingsApi';

export const PROVIDERS: { value: ModelProvider; label: string }[] = [
  { value: 'ollama', label: 'Ollama' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'vllm', label: 'vLLM (OpenAI-compatible)' },
];

export const providerLabel = (p: ModelProvider) => PROVIDERS.find((x) => x.value === p)?.label ?? p;

const queryKey = (tenantId: string | null) => ['model-settings', tenantId];

export const useModelSettings = () => {
  const { tenantId } = useAuth();
  return useQuery({
    queryKey: queryKey(tenantId),
    queryFn: () => getModelSettings(tenantId!),
    enabled: !!tenantId,
  });
};

/** The server's explanation of a rejected save (422/409/403), as one readable string. */
export const errorDetail = (err: unknown): string => {
  const detail = (err as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => (typeof d?.msg === 'string' ? d.msg : JSON.stringify(d))).join('; ');
  }
  return 'Saving failed. Please try again.';
};

export const useSaveModelSettings = () => {
  const { tenantId } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { llm?: LlmUpdate; embedding?: EmbeddingUpdate }) => updateModelSettings(tenantId!, body),
    onSuccess: (data: ModelSettings) => queryClient.setQueryData(queryKey(tenantId), data),
  });
};

/** api_key field of an update: omitted = keep, null = remove, string = set. */
export const apiKeyUpdate = (newKey: string, remove: boolean): { api_key?: string | null } =>
  remove ? { api_key: null } : newKey.trim() ? { api_key: newKey.trim() } : {};

/** '' (field left empty) means "use the server default". */
export const optionalNumber = (value: string): number | null => (value.trim() === '' ? null : Number(value));
export const optionalText = (value: string): string | null => (value.trim() === '' ? null : value.trim());

// --- Fields ------------------------------------------------------------------------------

const inputClass =
  'w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 placeholder:text-slate-500 ' +
  'focus:outline-none focus:ring-1 focus:ring-sky-500 disabled:opacity-60';

export const Field: React.FC<React.PropsWithChildren<{ id: string; label: string; hint?: string }>> = ({
  id,
  label,
  hint,
  children,
}) => (
  <div className="space-y-1">
    <label className="block text-slate-200" htmlFor={id}>
      {label}
    </label>
    {children}
    {hint && <p className="text-[11px] text-slate-500">{hint}</p>}
  </div>
);

export const TextInput: React.FC<React.InputHTMLAttributes<HTMLInputElement>> = (props) => (
  <input {...props} className={inputClass} />
);

export const ProviderSelect: React.FC<{
  id: string;
  value: string;
  serverDefault: ModelProvider;
  onChange: (value: string) => void;
  disabled?: boolean;
}> = ({ id, value, serverDefault, onChange, disabled }) => (
  <select id={id} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} className={inputClass}>
    <option value="">Server default ({providerLabel(serverDefault)})</option>
    {PROVIDERS.map((p) => (
      <option key={p.value} value={p.value}>
        {p.label}
      </option>
    ))}
  </select>
);

/** Only offered when the server allows tenants to choose endpoints. */
export const BaseUrlSelect: React.FC<{
  id: string;
  value: string;
  allowed: string[];
  onChange: (value: string) => void;
  disabled?: boolean;
}> = ({ id, value, allowed, onChange, disabled }) => (
  <select id={id} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} className={inputClass}>
    <option value="">Server default</option>
    {allowed.map((url) => (
      <option key={url} value={url}>
        {url}
      </option>
    ))}
  </select>
);

export const ApiKeyField: React.FC<{
  id: string;
  hasKey: boolean;
  value: string;
  remove: boolean;
  onChange: (value: string) => void;
  onRemoveChange: (remove: boolean) => void;
  disabled?: boolean;
}> = ({ id, hasKey, value, remove, onChange, onRemoveChange, disabled }) => (
  <Field
    id={id}
    label="API key"
    hint={
      hasKey
        ? 'A key is stored for this workspace. It is never shown; enter a new one to replace it.'
        : "Needed for OpenAI, unless it's the server's default provider. Stored keys are never shown."
    }
  >
    <TextInput
      id={id}
      type="password"
      autoComplete="off"
      value={value}
      placeholder={hasKey ? '•••••••• (stored)' : 'No key stored'}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled || remove}
    />
    {hasKey && (
      <label className="flex items-center gap-2 text-[11px] text-slate-300">
        <input
          type="checkbox"
          checked={remove}
          onChange={(e) => onRemoveChange(e.target.checked)}
          disabled={disabled}
          className="accent-sky-500"
        />
        Remove stored key
      </label>
    )}
  </Field>
);

export const FormStatus: React.FC<{ error: string | null; saved: boolean }> = ({ error, saved }) => (
  <>
    {error && (
      <p role="alert" className="text-[11px] text-red-400">
        {error}
      </p>
    )}
    {saved && !error && (
      <p role="status" className="text-[11px] text-emerald-400">
        Saved.
      </p>
    )}
  </>
);

export const SaveButton: React.FC<{ pending: boolean }> = ({ pending }) => (
  <button
    type="submit"
    disabled={pending}
    className="rounded bg-sky-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-sky-500 disabled:opacity-60"
  >
    {pending ? 'Saving…' : 'Save'}
  </button>
);

export const ReadOnlyNote: React.FC = () => (
  <p className="rounded border border-slate-800 bg-slate-900/60 px-2 py-1 text-[11px] text-slate-400">
    Only workspace owners can change these settings.
  </p>
);
