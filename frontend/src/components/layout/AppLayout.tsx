import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { useRegistrationInfo } from '../../services/registrationApi';
import { useAuth } from '../../store/auth';
import { WorkspaceSwitcher } from './WorkspaceSwitcher';

export const AppLayout: React.FC<React.PropsWithChildren> = ({ children }) => {
  const { user, isAuthenticated, logout } = useAuth();
  const registration = useRegistrationInfo();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-slate-800 px-4 py-3 flex items-center justify-between bg-slate-950/80 backdrop-blur">
        <Link to="/" className="font-semibold tracking-tight">
          RagNex
        </Link>
        <nav className="hidden md:flex items-center gap-4 text-sm text-slate-300">
          {!isAuthenticated && (
            <>
              <Link to="/login">Login</Link>
              {registration?.enabled !== false && <Link to="/register">Register</Link>}
            </>
          )}
          {isAuthenticated && (
            <>
              <Link to="/" className="text-xs text-slate-300 hover:text-slate-50">
                Dashboard
              </Link>
              <Link to="/chat" className="text-xs text-slate-300 hover:text-slate-50">
                Chat
              </Link>
              <Link to="/settings" className="text-xs text-slate-300 hover:text-slate-50">
                Settings
              </Link>
              <div className="flex items-center gap-3">
                <WorkspaceSwitcher />
                <span className="text-xs text-slate-400">{user?.email}</span>
                <button
                  type="button"
                  onClick={handleLogout}
                  className="rounded border border-slate-700 px-2 py-1 text-xs hover:bg-slate-800"
                >
                  Logout
                </button>
              </div>
            </>
          )}
        </nav>
        {isAuthenticated && (
          <button
            type="button"
            onClick={() => setMobileOpen((v) => !v)}
            className="md:hidden rounded border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800"
          >
            Menu
          </button>
        )}
      </header>
      {isAuthenticated && mobileOpen && (
        <nav className="md:hidden border-b border-slate-800 bg-slate-950 px-4 py-2 text-xs text-slate-300 space-y-2">
          <div className="flex gap-3">
            <Link to="/" onClick={() => setMobileOpen(false)} className="hover:text-slate-50">
              Dashboard
            </Link>
            <Link to="/chat" onClick={() => setMobileOpen(false)} className="hover:text-slate-50">
              Chat
            </Link>
            <Link to="/settings" onClick={() => setMobileOpen(false)} className="hover:text-slate-50">
              Settings
            </Link>
          </div>
          <WorkspaceSwitcher id="workspace-switcher-mobile" />
          <div className="flex items-center justify-between">
            <span className="text-slate-400">{user?.email}</span>
            <button
              type="button"
              onClick={handleLogout}
              className="rounded border border-slate-700 px-2 py-1 text-xs hover:bg-slate-800"
            >
              Logout
            </button>
          </div>
        </nav>
      )}
      <main className="flex-1 px-4 py-6 max-w-6xl w-full mx-auto">{children}</main>
    </div>
  );
};
