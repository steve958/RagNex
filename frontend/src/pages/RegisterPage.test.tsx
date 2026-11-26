import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { RegisterPage } from './RegisterPage';
import { RegistrationInfo } from '../services/registrationApi';

const register = vi.fn();
vi.mock('../store/auth', () => ({
  useAuth: () => ({ register }),
  NoTenantError: class NoTenantError extends Error {},
}));

let registration: RegistrationInfo | undefined;
vi.mock('../services/registrationApi', () => ({ useRegistrationInfo: () => registration }));

beforeEach(() => {
  registration = undefined; // not loaded yet / older server: offer sign-up
});

const fill = (password: string, confirm = password) => {
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'a@b.co' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } });
  fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: confirm } });
  fireEvent.submit(screen.getByRole('button', { name: 'Create account' }).closest('form')!);
};

describe('RegisterPage', () => {
  it('refuses passwords shorter than 8 characters before calling the server', async () => {
    render(<MemoryRouter><RegisterPage /></MemoryRouter>);
    fill('short');
    expect(await screen.findByText('Password must be at least 8 characters')).toBeInTheDocument();
    expect(register).not.toHaveBeenCalled();
  });

  it("shows the server's validation message", async () => {
    register.mockRejectedValueOnce({
      response: { status: 422, data: { detail: [{ loc: ['body', 'email'], msg: 'value is not a valid email address' }] } },
    });
    render(<MemoryRouter><RegisterPage /></MemoryRouter>);
    fill('long-enough-password');
    expect(await screen.findByText('value is not a valid email address')).toBeInTheDocument();
  });

  it('explains that sign-up is closed instead of showing the form', () => {
    registration = { enabled: false, email_domains: [] };
    render(<MemoryRouter><RegisterPage /></MemoryRouter>);
    expect(screen.getByText(/Sign-up is closed on this server/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Create account' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Login' })).toHaveAttribute('href', '/login');
  });

  it('says which email domains may sign up', () => {
    registration = { enabled: true, email_domains: ['example.org', 'corp.example'] };
    render(<MemoryRouter><RegisterPage /></MemoryRouter>);
    expect(screen.getByLabelText('Email')).toHaveAccessibleDescription(
      'Only addresses at example.org, corp.example can sign up.',
    );
  });

  it("shows the server's refusal, e.g. when sign-up closed after the page loaded", async () => {
    register.mockRejectedValueOnce({
      response: { status: 403, data: { detail: 'Sign-up is closed. Ask an administrator for an account.' } },
    });
    render(<MemoryRouter><RegisterPage /></MemoryRouter>);
    fill('long-enough-password');
    expect(await screen.findByText('Sign-up is closed. Ask an administrator for an account.')).toBeInTheDocument();
  });
});
