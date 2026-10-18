/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_STATIC?: string;
  readonly VITE_ERROR_REPORT_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
