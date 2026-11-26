import React, { useState } from 'react';

export const EmbeddingSettingsSection: React.FC = () => {
  const [provider, setProvider] = useState<'ollama' | 'openai' | 'vllm'>('openai');
  const [model, setModel] = useState('text-embedding-3-small');
  const [dimensions, setDimensions] = useState(1536);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
  };

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-slate-100 mb-1">Embedding configuration</h2>
        <p className="text-xs text-slate-400">
          Control which embedding model is used for document indexing and search. This form is local-only for now and
          will be wired to backend configuration in a later phase.
        </p>
      </div>
      <form onSubmit={handleSubmit} className="space-y-3 rounded border border-slate-800 bg-slate-950/60 p-3 text-xs">
        <div className="space-y-1">
          <label className="block text-slate-200" htmlFor="embed-provider">
            Provider
          </label>
          <select
            id="embed-provider"
            value={provider}
            onChange={(e) => setProvider(e.target.value as any)}
            className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:outline-none focus:ring-1 focus:ring-sky-500"
          >
            <option value="openai">OpenAI-compatible</option>
            <option value="ollama">Ollama</option>
            <option value="vllm">vLLM</option>
          </select>
        </div>
        <div className="space-y-1">
          <label className="block text-slate-200" htmlFor="embed-model">
            Model name
          </label>
          <input
            id="embed-model"
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:outline-none focus:ring-1 focus:ring-sky-500"
          />
        </div>
        <div className="space-y-1">
          <label className="block text-slate-200" htmlFor="embed-dim">
            Dimensions
          </label>
          <input
            id="embed-dim"
            type="number"
            min={1}
            max={8192}
            value={dimensions}
            onChange={(e) => setDimensions(parseInt(e.target.value, 10) || 0)}
            className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:outline-none focus:ring-1 focus:ring-sky-500"
          />
        </div>
        <div className="flex items-center justify-between pt-1">
          <p className="text-[11px] text-slate-500">Server-side embedding configuration will be added later.</p>
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