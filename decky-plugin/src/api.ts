import { callable } from "@decky/api";

export type Result = { ok: boolean; errors?: string[]; busy?: boolean; not_installed?: boolean;
  not_configured?: boolean; summary?: Record<string, number>; reports?: Result[] };

export type Conflict = { key: string; name: string; rel: string; detected: string;
  remote?: { device?: string; time?: string } | null };

export type Status = Result & {
  version?: string;
  configured?: boolean;
  device?: { id: string; name: string };
  remote?: string;
  remote_error?: string;
  running?: boolean;
  timer_enabled?: boolean;
  settings?: { on_game_exit: boolean; include_states: boolean; propagate_deletes: boolean };
  last_run?: { mode: string; finished: string; ok: boolean; errors: string[];
    summary?: Record<string, number>; skipped?: { key: string; reason: string }[] };
  conflicts?: Conflict[];
  sets?: { key: string; name: string; root: string }[];
};

export type RecentSave = { key: string; name: string; rel: string; size: number; device: string;
  modified: string; synced: string };

export type Snapshot = { id: string; time: string; device: string;
  files: { key: string; rel: string; size: number }[] };

export type Profile = { id: string; name: string; available: boolean; enabled: boolean; user: boolean;
  sets: { key: string; kind: string; root: string | null }[] };

export type Event = { time: string; action: string; key: string; name: string; rel: string;
  size?: number; device: string; source?: string; other?: string };

export const getStatus = callable<[], Status>("status");
export const getRecent = callable<[number], RecentSave[] | Result>("recent");
export const getActivity = callable<[number], Event[] | Result>("activity");
export const getHistory = callable<[number], Snapshot[] | Result>("history");
export const getProfiles = callable<[], Profile[] | Result>("profiles");
export const setProfile = callable<[string, string], Result>("set_profile");
export const setSetting = callable<[string, boolean], Result>("set_setting");
export const setTimer = callable<[boolean], Result>("set_timer");
export const syncNow = callable<[], Result>("sync_now");
export const gameExited = callable<[number], Result>("game_exited");
export const resumed = callable<[], Result>("resumed");
export const push = callable<[string | null, string | null], Result>("push");
export const pull = callable<[string | null, string | null], Result>("pull");
export const resolve = callable<[string, string | null, string | null], Result>("resolve");
export const restore = callable<[string, string, string], Result>("restore");

export function asList<T>(r: T[] | Result | null | undefined): T[] {
  return Array.isArray(r) ? r : [];
}
