import React, { createContext, useContext, useState, useCallback } from 'react';

interface Toast {
  id: number;
  message: string;
  type: 'success' | 'error' | 'info';
}

interface ToastContextValue {
  showToast: (message: string, type?: Toast['type']) => void;
}

const ToastContext = createContext<ToastContextValue | undefined>(undefined);

export const ToastProvider: React.FC<React.PropsWithChildren> = ({ children }) => {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [counter, setCounter] = useState(0);

  const showToast = useCallback((message: string, type: Toast['type'] = 'info') => {
    setCounter((c) => c + 1);
    const id = counter + 1;
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  }, [counter]);

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 top-2 z-50 flex justify-center sm:justify-end sm:pr-4">
        <div className="space-y-2">
          {toasts.map((t) => (
            <div
              key={t.id}
              className={`pointer-events-auto rounded border px-3 py-2 text-xs shadow-md ${
                t.type === 'success'
                  ? 'border-emerald-500 bg-emerald-950/70 text-emerald-100'
                  : t.type === 'error'
                  ? 'border-red-500 bg-red-950/70 text-red-100'
                  : 'border-slate-600 bg-slate-900/80 text-slate-100'
              }`}
            >
              {t.message}
            </div>
          ))}
        </div>
      </div>
    </ToastContext.Provider>
  );
};

export const useToast = (): ToastContextValue => {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return ctx;
};