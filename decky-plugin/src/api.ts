import { callable } from "@decky/api";

export type Result = { ok: boolean; errors?: string[]; busy?: boolean; not_installed?: boolean;
  not_configured?: boolean; summary?: Record<string, number>; reports?: Result[] };

export type Conflict = { provider: string; provider_name: string; key: string; name: string; rel: string;
  detected: string; remote?: { device?: string; time?: string } | null };

export type LastRun = { mode: string; finished: string; ok: boolean; errors: string[];
  summary?: Record<string, number>; skipped?: { key: string; reason: string }[] };

export type ProviderRow = { id: string; name: string; kind: "oauth" | "folder" | "ssh" | "rclone" | string;
  connected: boolean; target: string; error?: string; last_run?: LastRun };

export type Progress = { running: boolean; percent?: number; mode?: string; phase?: string; detail?: string;
  provider?: string; provider_name?: string; provider_index?: number; providers?: number; ok?: boolean;
  finished?: string; updated?: string };

export type AuthState = Result & { state: "idle" | "starting" | "waiting" | "done" | "error" | "cancelled";
  provider?: string; url?: string; target?: string };

export type Volume = { name: string; path: string; free: number; total: number; writable: boolean };

export type Status = Result & {
  version?: string;
  configured?: boolean;
  device?: { id: string; name: string };
  remote?: string;
  providers?: ProviderRow[];
  progress?: Progress;
  running?: boolean;
  timer_enabled?: boolean;
  settings?: { on_game_exit: boolean; include_states: boolean; propagate_deletes: boolean };
  last_run?: LastRun;
  conflicts?: Conflict[];
  sets?: { key: string; name: string; root: string }[];
};

export type RecentSave = { key: string; name: string; rel: string; size: number; device: string;
  modified: string; synced: string; providers?: string[] };

export type Snapshot = { id: string; time: string; device: string;
  files: { key: string; rel: string; size: number }[] };

export type Profile = { id: string; name: string; available: boolean; enabled: boolean; user: boolean;
  sets: { key: string; kind: string; root: string | null }[] };

export type Event = { time: string; action: string; key: string; name: string; rel: string;
  size?: number; device: string; source?: string; other?: string; provider?: string; provider_name?: string };

export const getStatus = callable<[], Status>("status");
export const getRecent = callable<[number], RecentSave[] | Result>("recent");
export const getActivity = callable<[number], Event[] | Result>("activity");
export const getHistory = callable<[number, string | null], Snapshot[] | Result>("history");
export const getProfiles = callable<[], Profile[] | Result>("profiles");
export const setProfile = callable<[string, string], Result>("set_profile");
export const setSetting = callable<[string, boolean], Result>("set_setting");
export const setTimer = callable<[boolean], Result>("set_timer");
export const syncNow = callable<[], Result>("sync_now");
export const gameExited = callable<[number], Result>("game_exited");
export const resumed = callable<[], Result>("resumed");
export const push = callable<[string | null, string | null], Result>("push");
export const pull = callable<[string | null, string | null, string | null], Result>("pull");
export const resolve = callable<[string, string | null, string | null, string | null], Result>("resolve");
export const restore = callable<[string, string, string, string | null], Result>("restore");
export const getProgress = callable<[], Progress>("progress");
export const getProviders = callable<[], { providers: ProviderRow[]; rclone_remotes: string[] } & Result>("providers");
export const getVolumes = callable<[], Volume[]>("volumes");
export const connect = callable<[string, string, Record<string, string>], AuthState>("connect");
export const connectStatus = callable<[], AuthState>("connect_status");
export const connectCancel = callable<[], Result>("connect_cancel");
export const disconnect = callable<[string], Result>("disconnect");

export function asList<T>(r: T[] | Result | null | undefined): T[] {
  return Array.isArray(r) ? r : [];
}

export type UpdateInfo = { current: string; latest?: string; newer: boolean; url?: string; notes?: string;
  published?: string; command: string; error?: string; checked?: string };
export const updateCheck = callable<[boolean], UpdateInfo>("update_check");
