import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { RegisterPage } from './RegisterPage';

const register = vi.fn();
vi.mock('../store/auth', () => ({
  useAuth: () => ({ register }),
  NoTenantError: class NoTenantError extends Error {},
}));

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
});
