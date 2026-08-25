// Drives the REAL store against hostile localStorage to confirm every failure
// path degrades to in-memory (never throws). Run via esbuild + node:
//
//   cd frontend
//   node_modules/.bin/esbuild tests/localstorage_degradation.ts --bundle \
//       --platform=node --format=esm --outfile=../artifacts/_degrade.mjs
//   node ../artifacts/_degrade.mjs
//
// (It is outside tsconfig `include: ["src"]`, so `npm run build` ignores it.)
import { loadPersisted, registerRun, getState } from "../src/store/store";

function mock(ls: unknown) {
  (globalThis as unknown as { localStorage: unknown }).localStorage = ls;
}
let pass = true;
function check(name: string, cond: boolean) {
  console.log((cond ? "PASS " : "FAIL ") + name);
  if (!cond) pass = false;
}

// 1) Corrupt payload on read
mock({ getItem: () => "{ not : valid json", setItem: () => {} });
const s1 = loadPersisted();
check("corrupt payload -> empty state, no throw", s1.order.length === 0 && s1.threadId === null);

// 2) Read throws (storage disabled / SecurityError)
mock({ getItem: () => { throw new Error("SecurityError: storage disabled"); }, setItem: () => {} });
let threw2 = false; let s2: ReturnType<typeof loadPersisted> | null = null;
try { s2 = loadPersisted(); } catch { threw2 = true; }
check("read throws -> caught, empty state", !threw2 && !!s2 && s2.order.length === 0);

// 3) Quota exceeded on write -> in-memory still works
mock({ getItem: () => null, setItem: () => { throw new Error("QuotaExceededError"); } });
let threw3 = false;
try { registerRun("run-quota"); } catch { threw3 = true; }
check("write quota throws -> caught (no throw)", !threw3);
check("in-memory updated despite write failure", !!getState().runs["run-quota"]);

// 4) Storage entirely absent
delete (globalThis as unknown as { localStorage?: unknown }).localStorage;
let threw4 = false;
try { loadPersisted(); registerRun("run-absent"); } catch { threw4 = true; }
check("absent storage -> no throw, in-memory works", !threw4 && !!getState().runs["run-absent"]);

console.log(pass ? "ALL DEGRADATION PATHS OK" : "SOME FAILED");
