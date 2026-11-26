import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { LoginPage } from './LoginPage';
import { RegistrationInfo } from '../services/registrationApi';

vi.mock('../store/auth', () => ({
  useAuth: () => ({ login: vi.fn() }),
  NoTenantError: class NoTenantError extends Error {},
}));

let registration: RegistrationInfo | undefined;
vi.mock('../services/registrationApi', () => ({ useRegistrationInfo: () => registration }));

const registerLink = () => screen.queryByRole('link', { name: 'Register' });

describe('LoginPage sign-up link', () => {
  it('offers sign-up when it is open', () => {
    registration = { enabled: true, email_domains: [] };
    render(<MemoryRouter><LoginPage /></MemoryRouter>);
    expect(registerLink()).toHaveAttribute('href', '/register');
  });

  it('keeps offering sign-up while the server has not said (the server still decides)', () => {
    registration = undefined;
    render(<MemoryRouter><LoginPage /></MemoryRouter>);
    expect(registerLink()).toBeInTheDocument();
  });

  it('hides sign-up when it is closed', () => {
    registration = { enabled: false, email_domains: [] };
    render(<MemoryRouter><LoginPage /></MemoryRouter>);
    expect(registerLink()).not.toBeInTheDocument();
  });
});
