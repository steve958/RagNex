import React, { useEffect, useState } from 'react';

import {
  apiKeyUpdate,
  ApiKeyField,
  BaseUrlSelect,
  errorDetail,
  Field,
  FormStatus,
  optionalNumber,
  optionalText,
  ProviderSelect,
  ReadOnlyNote,
  SaveButton,
  TextInput,
  useModelSettings,
  useSaveModelSettings,
} from './modelSettingsForm';

export const LlmSettingsSection: React.FC = () => {
  const { data, isLoading, isError } = useModelSettings();
  const save = useSaveModelSettings();

  // Form values are the tenant's overrides; '' = use the server default.
  const [provider, setProvider] = useState('');
  const [model, setModel] = useState('');
  const [temperature, setTemperature] = useState('');
  const [maxTokens, setMaxTokens] = useState('');
  const [contextWindow, setContextWindow] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [removeKey, setRemoveKey] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const overrides = data?.llm.overrides;
  useEffect(() => {
    if (!overrides) return;
    setProvider(overrides.provider ?? '');
    setModel(overrides.model ?? '');
    setTemperature(overrides.temperature?.toString() ?? '');
    setMaxTokens(overrides.max_tokens?.toString() ?? '');
    setContextWindow(overrides.context_window?.toString() ?? '');
    setBaseUrl(overrides.base_url ?? '');
    setApiKey('');
    setRemoveKey(false);
  }, [overrides]);

  if (isLoading) return <p className="text-xs text-slate-400">Loading LLM settings…</p>;
  if (isError || !data) return <p className="text-xs text-red-400">Failed to load LLM settings.</p>;

  // What an empty field falls back to.
  const defaults = data.llm.defaults;
  const readOnly = !data.can_edit;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaved(false);
    try {
      await save.mutateAsync({
        llm: {
          provider: (optionalText(provider) as typeof defaults.provider | null) ?? undefined,
          model: optionalText(model) ?? undefined,
          temperature: optionalNumber(temperature) ?? undefined,
          max_tokens: optionalNumber(maxTokens) ?? undefined,
          context_window: optionalNumber(contextWindow) ?? undefined,
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
        <h2 className="mb-1 text-sm font-semibold text-slate-100">LLM</h2>
        <p className="text-xs text-slate-400">
          The model that writes chat answers for this workspace. Leave a field empty to use the server default, shown
          in grey.
        </p>
      </div>
      {readOnly && <ReadOnlyNote />}
      <form onSubmit={handleSubmit} className="space-y-3 rounded border border-slate-800 bg-slate-950/60 p-3 text-xs">
        <fieldset disabled={readOnly || save.isPending} className="space-y-3">
          <Field id="llm-provider" label="Provider">
            <ProviderSelect
              id="llm-provider"
              value={provider}
              serverDefault={defaults.provider}
              onChange={setProvider}
            />
          </Field>
          <Field id="llm-model" label="Model">
            <TextInput
              id="llm-model"
              value={model}
              placeholder={defaults.model}
              onChange={(e) => setModel(e.target.value)}
            />
          </Field>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field id="llm-temperature" label="Temperature" hint="0 = focused, 2 = creative">
              <TextInput
                id="llm-temperature"
                type="number"
                min={0}
                max={2}
                step={0.05}
                value={temperature}
                placeholder={String(defaults.temperature)}
                onChange={(e) => setTemperature(e.target.value)}
              />
            </Field>
            <Field id="llm-max-tokens" label="Max answer tokens">
              <TextInput
                id="llm-max-tokens"
                type="number"
                min={16}
                value={maxTokens}
                placeholder={String(defaults.max_tokens)}
                onChange={(e) => setMaxTokens(e.target.value)}
              />
            </Field>
            <Field id="llm-context-window" label="Context window" hint="The model's real limit, in tokens">
              <TextInput
                id="llm-context-window"
                type="number"
                min={1024}
                value={contextWindow}
                placeholder={String(defaults.context_window)}
                onChange={(e) => setContextWindow(e.target.value)}
              />
            </Field>
          </div>
          {data.allowed_base_urls.length > 0 && (
            <Field id="llm-base-url" label="Endpoint">
              <BaseUrlSelect id="llm-base-url" value={baseUrl} allowed={data.allowed_base_urls} onChange={setBaseUrl} />
            </Field>
          )}
          <ApiKeyField
            id="llm-api-key"
            hasKey={data.llm.has_api_key}
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
