import { Component, type ReactNode } from "react";

interface Props { children: ReactNode }
interface S { error: Error | null }

// Any render exception is caught here instead of white-screening the app.
export class ErrorBoundary extends Component<Props, S> {
  state: S = { error: null };

  static getDerivedStateFromError(error: Error): S {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ maxWidth: 600, margin: "80px auto", padding: 24, fontFamily: "system-ui" }}>
          <h2 style={{ marginBottom: 8 }}>Something went wrong</h2>
          <p style={{ color: "#666", marginBottom: 16 }}>
            The UI hit an unexpected error. Reload to continue — your run keeps
            executing on the server.
          </p>
          <pre style={{ background: "#f5f5f4", padding: 12, borderRadius: 8, overflow: "auto", fontSize: 12 }}>
            {this.state.error.message}
          </pre>
          <button
            onClick={() => this.setState({ error: null })}
            style={{ marginTop: 16, padding: "8px 16px", borderRadius: 8, border: "1px solid #ccc", cursor: "pointer" }}
          >
            Dismiss
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
