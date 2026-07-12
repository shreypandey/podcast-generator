import { USE_MOCK, type Backend } from "./backend";
import { mockBackend } from "./mock";
import { realBackend } from "./real";

// Single entry point. Flip VITE_USE_MOCK=1 to run the whole UI against the in-browser mock.
export const api: Backend = USE_MOCK ? mockBackend : realBackend;
export { USE_MOCK };
export { ApiErr } from "./backend";
export * from "./types";
