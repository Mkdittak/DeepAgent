// Login + token-exchange screens (Stytch prebuilt B2B UI, Discovery flow).
//
// The same <StytchB2B> component serves both: on "/" it renders the
// email-magic-link + Google OAuth form; on "/authenticate" (the redirect URL
// registered in the dashboard) it reads the token from the query string,
// completes the discovery exchange, and establishes the member session.
// Config shape verified against @stytch/vanilla-js 6.3.0 types
// (StytchB2BUIConfig / CommonB2BLoginConfig).

import { useEffect } from "react";
import {
  AuthFlowType,
  B2BOAuthProviders,
  B2BProducts,
  StytchB2B,
  useStytchMemberSession,
  type StytchB2BUIConfig,
} from "@stytch/react/b2b";
import "./Login.css";

const REDIRECT_URL = `${window.location.origin}/authenticate`;

const config: StytchB2BUIConfig = {
  products: [B2BProducts.emailMagicLinks, B2BProducts.oauth],
  authFlowType: AuthFlowType.Discovery,
  sessionOptions: { sessionDurationMinutes: 480 },
  emailMagicLinksOptions: { discoveryRedirectURL: REDIRECT_URL },
  oauthOptions: {
    providers: [{ type: B2BOAuthProviders.Google }],
    discoveryRedirectURL: REDIRECT_URL,
  },
};

const styles = {
  container: { width: "100%", maxWidth: "420px" },
  fontFamily: "inherit",
};

function Frame({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="da-login">
      <div className="da-login-card">
        <div className="da-login-brand">DeepAgent</div>
        <div className="da-login-title">{title}</div>
        {hint && <div className="da-login-hint">{hint}</div>}
        {children}
      </div>
    </div>
  );
}

export function Login() {
  return (
    <Frame title="Sign in to your workspace" hint="Use your work email or Google account.">
      <StytchB2B config={config} styles={styles} />
    </Frame>
  );
}

// /authenticate: the token-exchange handler. Once the session exists the URL
// is rewritten to "/" without a reload so the shell renders in place.
export function Authenticate() {
  const { session } = useStytchMemberSession();
  useEffect(() => {
    if (session) window.history.replaceState(null, "", "/");
  }, [session]);
  return (
    <Frame title="Signing you in…" hint="Completing authentication with Stytch.">
      <StytchB2B config={config} styles={styles} />
    </Frame>
  );
}
