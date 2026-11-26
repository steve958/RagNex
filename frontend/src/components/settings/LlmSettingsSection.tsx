import React, { useState } from 'react';

export const LlmSettingsSection: React.FC = () => {
  const [provider, setProvider] = useState<'ollama' | 'openai' | 'vllm'>('ollama');
  const [model, setModel] = useState('llama3');
  const [temperature, setTemperature] = useState(0.2);
  const [maxTokens, setMaxTokens] = useState(2048);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    // Not yet wired to backend; for now just keep local state.
  };

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-slate-100 mb-1">LLM configuration</h2>
        <p className="text-xs text-slate-400">
          Configure the default large language model used for chat and summarization. This UI is currently local-only
          and not yet wired to a backend configuration API.
        </p>
      </div>
      <form onSubmit={handleSubmit} className="space-y-3 rounded border border-slate-800 bg-slate-950/60 p-3 text-xs">
        <div className="space-y-1">
          <label className="block text-slate-200" htmlFor="llm-provider">
            Provider
          </label>
          <select
            id="llm-provider"
            value={provider}
            onChange={(e) => setProvider(e.target.value as any)}
            className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:outline-none focus:ring-1 focus:ring-sky-500"
          >
            <option value="ollama">Ollama</option>
            <option value="openai">OpenAI-compatible</option>
            <option value="vllm">vLLM (OpenAI-compatible)</option>
          </select>
        </div>
        <div className="space-y-1">
          <label className="block text-slate-200" htmlFor="llm-model">
            Model name
          </label>
          <input
            id="llm-model"
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:outline-none focus:ring-1 focus:ring-sky-500"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <label className="block text-slate-200" htmlFor="llm-temp">
              Temperature
            </label>
            <input
              id="llm-temp"
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={temperature}
              onChange={(e) => setTemperature(parseFloat(e.target.value) || 0)}
              className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:outline-none focus:ring-1 focus:ring-sky-500"
            />
          </div>
          <div className="space-y-1">
            <label className="block text-slate-200" htmlFor="llm-max-tokens">
              Max tokens
            </label>
            <input
              id="llm-max-tokens"
              type="number"
              min={1}
              max={32768}
              value={maxTokens}
              onChange={(e) => setMaxTokens(parseInt(e.target.value, 10) || 0)}
              className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:outline-none focus:ring-1 focus:ring-sky-500"
            />
          </div>
        </div>
        <div className="flex items-center justify-between pt-1">
          <p className="text-[11px] text-slate-500">Persisting these settings to the server will be added later.</p>
          <button
            type="submit"
            disabled
            className="rounded bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-400 cursor-not-allowed"
          >
            Save (coming soon)
          </button>
        </div>
      </form>
    </div>
  );
};