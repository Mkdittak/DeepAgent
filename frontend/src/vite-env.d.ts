/// <reference types="vite/client" />

interface ImportMetaEnv {
  // Override the API origin. "" = same-origin (relative URLs, e.g. behind a
  // reverse proxy); or a full origin like "https://api.example.com".
  readonly VITE_API_BASE?: string;
  // Stytch B2B public token. Unset = the UI boots without auth (pair with a
  // backend running AUTH_ENABLED=false).
  readonly VITE_STYTCH_PUBLIC_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
