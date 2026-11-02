// Browser sign-in for cloud providers, tracked in the background (no dialog: a dialog on top of Steam's browser
// gets dismissed by a tap, which used to cancel the sign-in before Google could redirect back to rclone).
import { Navigation } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { AuthState, ProviderRow, connect, connectCancel, connectStatus } from "./api";

type SignIn = { provider: string; name: string; state: AuthState["state"]; url?: string; error?: string } | null;

let current: SignIn = null;
let timer: ReturnType<typeof setInterval> | undefined;
let onDone: (() => void) | undefined;
const listeners = new Set<() => void>();

function set(next: SignIn) {
  current = next;
  listeners.forEach((f) => f());
}

function stopPolling() {
  if (timer) clearInterval(timer);
  timer = undefined;
}

async function poll() {
  if (!current) return stopPolling();
  let s: AuthState;
  try { s = await connectStatus(); } catch { return; }
  if (!current || (s.provider && s.provider !== current.provider)) return;
  if (s.state === "done") {
    stopPolling();
    toaster.toast({ title: "Extra Life", body: `${current.name} connected. The next sync includes it.` });
    set(null);
    onDone?.();
  } else if (s.state === "error" || s.state === "idle" || s.state === "cancelled") {
    stopPolling();
    const err = s.errors?.[0] ?? "Sign-in ended";
    if (s.state === "error") toaster.toast({ title: `Extra Life: ${current.name}`, body: err, critical: true });
    set(null);
    onDone?.();
  } else if (s.url && s.url !== current.url) {
    set({ ...current, url: s.url, state: s.state });
  }
}

export async function startSignIn(p: ProviderRow, done: () => void) {
  if (current) await cancelSignIn();
  onDone = done;
  set({ provider: p.id, name: p.name, state: "starting" });
  toaster.toast({ title: "Extra Life", body: `Opening the ${p.name} sign-in page…` });
  let a: AuthState;
  try { a = await connect(p.id, "oauth", {}); } catch (e) { a = { ok: false, state: "error", errors: [String(e)] }; }
  if (a.state === "error" || !a.url) {
    toaster.toast({ title: `Extra Life: ${p.name}`, body: a.errors?.[0] ?? "Couldn't start the sign-in", critical: true });
    set(null);
    return;
  }
  set({ provider: p.id, name: p.name, state: "waiting", url: a.url });
  Navigation.NavigateToExternalWeb(a.url);
  stopPolling();
  timer = setInterval(poll, 1000);
}

export function reopenSignIn() {
  if (current?.url) Navigation.NavigateToExternalWeb(current.url);
}

export async function cancelSignIn() {
  stopPolling();
  set(null);
  await connectCancel();
  onDone?.();
}

export function useSignIn(): SignIn {
  const [v, setV] = useState(current);
  useEffect(() => {
    const f = () => setV(current);
    listeners.add(f);
    return () => { listeners.delete(f); };
  }, []);
  return v;
}
