import React, { useState } from 'react';

import { LlmSettingsSection } from '../components/settings/LlmSettingsSection';
import { EmbeddingSettingsSection } from '../components/settings/EmbeddingSettingsSection';
import { ApiKeysSection } from '../components/settings/ApiKeysSection';
import { TeamSettingsSection } from '../components/settings/TeamSettingsSection';

type TabId = 'llm' | 'embeddings' | 'api-keys' | 'team';

const TABS: { id: TabId; label: string }[] = [
  { id: 'llm', label: 'LLM' },
  { id: 'embeddings', label: 'Embeddings' },
  { id: 'api-keys', label: 'API keys' },
  { id: 'team', label: 'Workspace' },
];

export const SettingsPage: React.FC = () => {
  const [tab, setTab] = useState<TabId>('llm');

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold mb-1">Settings</h1>
          <p className="text-sm text-slate-300">Configure models, API keys, and team/tenant access.</p>
        </div>
      </div>

      <div className="flex flex-col gap-4 md:flex-row">
        <aside className="w-full md:w-48 shrink-0">
          <nav className="flex overflow-auto md:flex-col gap-2 text-xs">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
                className={`rounded px-3 py-1.5 text-left hover:bg-slate-800 ${
                  tab === t.id ? 'bg-slate-800 text-slate-50' : 'bg-slate-900 text-slate-300'
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>
        </aside>
        <section className="flex-1 min-w-0">
          {tab === 'llm' && <LlmSettingsSection />}
          {tab === 'embeddings' && <EmbeddingSettingsSection />}
          {tab === 'api-keys' && <ApiKeysSection />}
          {tab === 'team' && <TeamSettingsSection />}
        </section>
      </div>
    </div>
  );
};