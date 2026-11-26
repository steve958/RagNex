import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { NoTenantError, useAuth } from '../store/auth';
import { errorDetail } from '../services/errors';
import { useRegistrationInfo } from '../services/registrationApi';

// Matches the backend's NewPassword rule (backend/app/core/validation.py).
const MIN_PASSWORD_LENGTH = 8;

export const RegisterPage: React.FC = () => {
  const { register } = useAuth();
  const registration = useRegistrationInfo();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters`);
      return;
    }
    if (password !== confirm) {
      setError('Passwords do not match');
      return;
    }
    setSubmitting(true);
    try {
      await register(email, password);
      navigate('/');
    } catch (err: unknown) {
      setError(err instanceof NoTenantError ? err.message : errorDetail(err, 'Registration failed'));
    } finally {
      setSubmitting(false);
    }
  };

  if (registration?.enabled === false) {
    return (
      <div className="max-w-md mx-auto">
        <h1 className="text-2xl font-semibold mb-4">Register</h1>
        <p className="text-sm text-slate-300">
          Sign-up is closed on this server. Ask an administrator for an account.
        </p>
        <p className="mt-4 text-sm text-slate-300">
          Already have an account?{' '}
          <Link to="/login" className="text-sky-400 hover:underline">
            Login
          </Link>
          .
        </p>
      </div>
    );
  }

  const domains = registration?.email_domains ?? [];

  return (
    <div className="max-w-md mx-auto">
      <h1 className="text-2xl font-semibold mb-4">Register</h1>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1">
          <label className="block text-sm text-slate-300" htmlFor="email">
            Email
          </label>
          <input
            id="email"
            type="email"
            className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-50 focus:outline-none focus:ring-1 focus:ring-sky-500"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-describedby={domains.length ? 'email-hint' : undefined}
            required
          />
          {domains.length > 0 && (
            <p id="email-hint" className="text-xs text-slate-500">
              Only addresses at {domains.join(', ')} can sign up.
            </p>
          )}
        </div>
        <div className="space-y-1">
          <label className="block text-sm text-slate-300" htmlFor="password">
            Password
          </label>
          <input
            id="password"
            type="password"
            className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-50 focus:outline-none focus:ring-1 focus:ring-sky-500"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={MIN_PASSWORD_LENGTH}
            maxLength={1024}
            aria-describedby="password-hint"
            required
          />
          <p id="password-hint" className="text-xs text-slate-500">
            At least {MIN_PASSWORD_LENGTH} characters.
          </p>
        </div>
        <div className="space-y-1">
          <label className="block text-sm text-slate-300" htmlFor="confirm">
            Confirm password
          </label>
          <input
            id="confirm"
            type="password"
            className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-50 focus:outline-none focus:ring-1 focus:ring-sky-500"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
          />
        </div>
        {error && <p className="text-sm text-red-400">{error}</p>}
        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded bg-sky-600 px-3 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-60"
        >
          {submitting ? 'Creating account…' : 'Create account'}
        </button>
      </form>
      <p className="mt-4 text-sm text-slate-300">
        Already have an account?{' '}
        <Link to="/login" className="text-sky-400 hover:underline">
          Login
        </Link>
        .
      </p>
    </div>
  );
};
