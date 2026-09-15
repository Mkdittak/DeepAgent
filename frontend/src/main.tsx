import React from "react";
import ReactDOM from "react-dom/client";
import { StytchB2BProvider } from "@stytch/react/b2b";
import App from "./App.tsx";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { getStytchClient } from "./auth/stytch";

// The provider mounts only when VITE_STYTCH_PUBLIC_TOKEN is configured (and
// the client initialized). Otherwise the app renders exactly as before —
// the unconfigured path is the no-auth path, mirroring AUTH_ENABLED=false.
const stytch = getStytchClient();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      {stytch ? (
        <StytchB2BProvider stytch={stytch}>
          <App />
        </StytchB2BProvider>
      ) : (
        <App />
      )}
    </ErrorBoundary>
  </React.StrictMode>
);
