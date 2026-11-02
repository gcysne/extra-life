// One poller for the sync progress, shared by the status bar icon and the panel.
import { useEffect, useState } from "react";
import { Progress, getProgress } from "./api";

const RUNNING_MS = 700;
const IDLE_MS = 2000;
const LINGER_MS = 2500;      // keep showing the full bar briefly after a sync ends, then hide

export type View = Progress & { visible: boolean };

let state: View = { running: false, visible: false };
let lingerUntil = 0;
let timer: ReturnType<typeof setTimeout> | undefined;
let stopped = true;
const listeners = new Set<() => void>();

function set(next: View) {
  state = next;
  listeners.forEach((f) => f());
}

async function tick() {
  let p: Progress = { running: false };
  try { p = await getProgress(); } catch { /* backend reloading */ }
  const now = Date.now();
  if (state.running && !p.running) lingerUntil = now + LINGER_MS;
  const visible = !!p.running || now < lingerUntil;
  set({ ...p, percent: p.running ? p.percent ?? 0 : visible ? 100 : p.percent, visible });
  if (!stopped) timer = setTimeout(tick, p.running || visible ? RUNNING_MS : IDLE_MS);
}

export function startProgress() {
  if (!stopped) return;
  stopped = false;
  tick();
}

export function stopProgress() {
  stopped = true;
  if (timer) clearTimeout(timer);
}

/** Poll right away (after starting a sync), instead of waiting for the idle interval. */
export function pokeProgress() {
  if (stopped) return;
  if (timer) clearTimeout(timer);
  tick();
}

export function useProgress(): View {
  const [v, setV] = useState(state);
  useEffect(() => {
    const f = () => setV(state);
    listeners.add(f);
    return () => { listeners.delete(f); };
  }, []);
  return v;
}

const PHASES: Record<string, string> = {
  starting: "Starting", connecting: "Connecting", comparing: "Comparing saves", transferring: "Transferring",
  finishing: "Finishing", done: "Done",
};

export function progressText(p: Progress): string {
  const parts = [];
  if (p.provider_name) parts.push(p.provider_name);
  parts.push(PHASES[p.phase ?? ""] ?? p.phase ?? "");
  if (p.detail) parts.push(p.detail);
  return parts.filter(Boolean).join(" · ");
}
