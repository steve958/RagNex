import React, { useEffect, useState } from 'react';

import {
  apiKeyUpdate,
  ApiKeyField,
  BaseUrlSelect,
  errorDetail,
  Field,
  FormStatus,
  optionalText,
  ProviderSelect,
  ReadOnlyNote,
  SaveButton,
  TextInput,
  useModelSettings,
  useSaveModelSettings,
} from './modelSettingsForm';

export const EmbeddingSettingsSection: React.FC = () => {
  const { data, isLoading, isError } = useModelSettings();
  const save = useSaveModelSettings();

  // Form values are the tenant's overrides; '' = use the server default.
  const [provider, setProvider] = useState('');
  const [model, setModel] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [removeKey, setRemoveKey] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const overrides = data?.embedding.overrides;
  useEffect(() => {
    if (!overrides) return;
    setProvider(overrides.provider ?? '');
    setModel(overrides.model ?? '');
    setBaseUrl(overrides.base_url ?? '');
    setApiKey('');
    setRemoveKey(false);
  }, [overrides]);

  if (isLoading) return <p className="text-xs text-slate-400">Loading embedding settings…</p>;
  if (isError || !data) return <p className="text-xs text-red-400">Failed to load embedding settings.</p>;

  const { defaults, locked, dimension } = data.embedding;
  const readOnly = !data.can_edit;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaved(false);
    try {
      await save.mutateAsync({
        embedding: {
          provider: (optionalText(provider) as typeof defaults.provider | null) ?? undefined,
          model: optionalText(model) ?? undefined,
          base_url: optionalText(baseUrl),
          ...apiKeyUpdate(apiKey, removeKey),
        },
      });
      setSaved(true);
    } catch (err) {
      setError(errorDetail(err));
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h2 className="mb-1 text-sm font-semibold text-slate-100">Embeddings</h2>
        <p className="text-xs text-slate-400">
          The model that turns documents and questions into vectors for search. It must produce {dimension}-dimensional
          vectors; a new model is checked when you save. Leave a field empty to use the server default, shown in grey.
        </p>
      </div>
      {readOnly && <ReadOnlyNote />}
      {locked && (
        <p className="rounded border border-amber-900/60 bg-amber-950/40 px-2 py-1 text-[11px] text-amber-200">
          This workspace has indexed documents, so the embedding model can't be changed: their vectors were made with
          the current model and wouldn't match searches with a different one. The API key and endpoint can still be
          updated.
        </p>
      )}
      <form onSubmit={handleSubmit} className="space-y-3 rounded border border-slate-800 bg-slate-950/60 p-3 text-xs">
        <fieldset disabled={readOnly || save.isPending} className="space-y-3">
          <Field id="emb-provider" label="Provider">
            <ProviderSelect
              id="emb-provider"
              value={provider}
              serverDefault={defaults.provider}
              onChange={setProvider}
              disabled={locked}
            />
          </Field>
          <Field id="emb-model" label="Model">
            <TextInput
              id="emb-model"
              value={model}
              placeholder={defaults.model}
              onChange={(e) => setModel(e.target.value)}
              disabled={locked}
            />
          </Field>
          {data.allowed_base_urls.length > 0 && (
            <Field id="emb-base-url" label="Endpoint">
              <BaseUrlSelect id="emb-base-url" value={baseUrl} allowed={data.allowed_base_urls} onChange={setBaseUrl} />
            </Field>
          )}
          <ApiKeyField
            id="emb-api-key"
            hasKey={data.embedding.has_api_key}
            keyReadable={data.embedding.api_key_readable ?? true}
            value={apiKey}
            remove={removeKey}
            onChange={setApiKey}
            onRemoveChange={setRemoveKey}
          />
        </fieldset>
        <FormStatus error={error} saved={saved} />
        {!readOnly && <SaveButton pending={save.isPending} />}
      </form>
    </div>
  );
};
