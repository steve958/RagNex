import React from 'react';

interface State {
  hasError: boolean;
}

export class ErrorBoundary extends React.Component<React.PropsWithChildren, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // In a real app we might log this to an error reporting service.
    // eslint-disable-next-line no-console
    console.error('ErrorBoundary caught error', error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-slate-950 text-slate-100">
          <div className="max-w-md rounded border border-slate-800 bg-slate-900 p-6 text-center text-sm">
            <h1 className="mb-2 text-lg font-semibold">Something went wrong</h1>
            <p className="text-slate-300 mb-3">
              An unexpected error occurred while rendering the UI. Try refreshing the page. If the problem persists,
              please contact support.
            </p>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}