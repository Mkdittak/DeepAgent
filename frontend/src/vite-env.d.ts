/// <reference types="vite/client" />

interface ImportMetaEnv {
  // Override the API origin. "" = same-origin (relative URLs, e.g. behind a
  // reverse proxy); or a full origin like "https://api.example.com".
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
