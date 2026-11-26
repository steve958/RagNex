import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { LlmSettingsSection } from './LlmSettingsSection';
import { EmbeddingSettingsSection } from './EmbeddingSettingsSection';
import { getModelSettings, ModelSettings, updateModelSettings } from '../../services/modelSettingsApi';

vi.mock('../../store/auth', () => ({ useAuth: () => ({ tenantId: 't1' }) }));
vi.mock('../../services/modelSettingsApi', () => ({
  getModelSettings: vi.fn(),
  updateModelSettings: vi.fn(),
}));

const settings = (overrides: Partial<ModelSettings> = {}): ModelSettings => ({
  can_edit: true,
  allowed_base_urls: [],
  llm: {
    effective: { provider: 'ollama', model: 'mistral', temperature: 0.2, max_tokens: 2048, context_window: 8192, base_url: null },
    defaults: { provider: 'ollama', model: 'llama3', temperature: 0.2, max_tokens: 2048, context_window: 8192 },
    overrides: { model: 'mistral' },
    has_api_key: false,
  },
  embedding: {
    effective: { provider: 'ollama', model: 'bge-m3', base_url: null },
    defaults: { provider: 'ollama', model: 'bge-m3' },
    overrides: {},
    has_api_key: false,
    locked: false,
    dimension: 1024,
  },
  ...overrides,
});

const renderWith = (ui: React.ReactElement, data: ModelSettings) => {
  vi.mocked(getModelSettings).mockResolvedValue(data);
  vi.mocked(updateModelSettings).mockResolvedValue(data);
  return render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>);
};

beforeEach(() => {
  vi.mocked(updateModelSettings).mockReset();
});

describe('LlmSettingsSection', () => {
  it('shows overrides as values and server defaults as placeholders', async () => {
    renderWith(<LlmSettingsSection />, settings());

    const model = await screen.findByLabelText('Model');
    expect(model).toHaveValue('mistral');
    expect(model).toHaveAttribute('placeholder', 'llama3');
    expect(screen.getByLabelText('Context window')).toHaveValue(null);
    expect(screen.getByLabelText('Context window')).toHaveAttribute('placeholder', '8192');
    expect(screen.getByRole('option', { name: 'Server default (Ollama)' })).toBeInTheDocument();
    // No allowlisted endpoints: no endpoint picker at all.
    expect(screen.queryByLabelText('Endpoint')).not.toBeInTheDocument();
  });

  it('sends only the fields that are set, and keeps the stored API key by default', async () => {
    renderWith(<LlmSettingsSection />, settings());

    fireEvent.change(await screen.findByLabelText('Context window'), { target: { value: '32768' } });
    fireEvent.change(screen.getByLabelText('Model'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(updateModelSettings).toHaveBeenCalled());
    const [tenant, body] = vi.mocked(updateModelSettings).mock.calls[0];
    expect(tenant).toBe('t1');
    expect(body.llm).toMatchObject({ context_window: 32768, base_url: null });
    expect(body.llm).not.toHaveProperty('api_key');
    expect(body.llm?.model).toBeUndefined(); // emptied = back to the server default
    expect(await screen.findByText('Saved.')).toBeInTheDocument();
  });

  it('sets a new API key, or removes the stored one', async () => {
    const withKey = settings();
    withKey.llm.has_api_key = true;
    renderWith(<LlmSettingsSection />, withKey);

    const key = await screen.findByLabelText('API key');
    expect(key).toHaveAttribute('type', 'password');
    expect(key).toHaveValue('');

    fireEvent.change(key, { target: { value: 'sk-new' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(updateModelSettings).toHaveBeenCalledTimes(1));
    expect(vi.mocked(updateModelSettings).mock.calls[0][1].llm?.api_key).toBe('sk-new');

    fireEvent.click(screen.getByLabelText('Remove stored key'));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(updateModelSettings).toHaveBeenCalledTimes(2));
    expect(vi.mocked(updateModelSettings).mock.calls[1][1].llm?.api_key).toBeNull();
  });

  it("shows the server's reason when a save is rejected", async () => {
    renderWith(<LlmSettingsSection />, settings());
    vi.mocked(updateModelSettings).mockRejectedValue({
      response: { status: 422, data: { detail: 'LLM: an API key is required to use OpenAI with this workspace.' } },
    });

    await screen.findByLabelText('Model');
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('an API key is required');
  });

  it('is read-only for members', async () => {
    renderWith(<LlmSettingsSection />, settings({ can_edit: false }));

    expect(await screen.findByLabelText('Model')).toBeDisabled();
    expect(screen.getByText(/Only workspace owners/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();
  });

  it('offers only allowlisted endpoints', async () => {
    renderWith(<LlmSettingsSection />, settings({ allowed_base_urls: ['http://gpu-box:11434'] }));

    const endpoint = await screen.findByLabelText('Endpoint');
    expect([...(endpoint as HTMLSelectElement).options].map((o) => o.value)).toEqual(['', 'http://gpu-box:11434']);
  });
});

describe('EmbeddingSettingsSection', () => {
  it('locks the model once documents are indexed but still allows a new API key', async () => {
    const locked = settings();
    locked.embedding.locked = true;
    renderWith(<EmbeddingSettingsSection />, locked);

    expect(await screen.findByText(/has indexed documents/)).toBeInTheDocument();
    expect(screen.getByLabelText('Model')).toBeDisabled();
    expect(screen.getByLabelText('Provider')).toBeDisabled();
    expect(screen.getByLabelText('API key')).not.toBeDisabled();

    fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'emb-key' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(updateModelSettings).toHaveBeenCalled());
    expect(vi.mocked(updateModelSettings).mock.calls[0][1]).toEqual({
      embedding: { provider: undefined, model: undefined, base_url: null, api_key: 'emb-key' },
    });
  });
});
