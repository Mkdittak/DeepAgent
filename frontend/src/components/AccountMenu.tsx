// Org name + switch-org / logout menu. Only ever rendered when auth is
// configured (it uses the Stytch hooks, which need the provider above it).
//
// Hook / method names verified against @stytch/react 20.3.0 and
// @stytch/vanilla-js 6.3.0: useStytchOrganization().organization
// .organization_name, useStytchB2BClient().session.revoke().
//
// "Switch organization" = revoke the session and return to the Discovery
// login, where the member picks another org. (session.exchange() could swap
// in place, but listing a member's other orgs needs a discovery intermediate
// session, which a logged-in member doesn't hold — the round-trip is the
// straightforward path.)

import { useEffect, useRef, useState } from "react";
import { useStytchB2BClient, useStytchMember, useStytchOrganization } from "@stytch/react/b2b";
import { newChat } from "../net/controller";

export function AccountMenu() {
  const stytch = useStytchB2BClient();
  const { organization } = useStytchOrganization();
  const { member } = useStytchMember();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const signOut = async () => {
    setBusy(true);
    try {
      // Clear this browser's cached transcript first so the next member on
      // this machine never sees the previous one's conversation.
      newChat();
      await stytch.session.revoke();
    } catch (e) {
      console.error("sign-out failed", e);
    } finally {
      setBusy(false);
      setOpen(false);
    }
  };

  const orgName = organization?.organization_name ?? "…";
  const email = member?.email_address ?? "";

  return (
    <div className="da-account" ref={ref}>
      <button
        className="da-account-btn"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        title={email}
      >
        <span className="da-account-org">{orgName}</span>
        <span className="da-account-caret" aria-hidden>▾</span>
      </button>
      {open && (
        <div className="da-account-menu" role="menu">
          {email && <div className="da-menu-label">{email}</div>}
          <button role="menuitem" disabled={busy} onClick={signOut}>
            Switch organization
          </button>
          <button role="menuitem" className="is-danger" disabled={busy} onClick={signOut}>
            Log out
          </button>
        </div>
      )}
    </div>
  );
}
