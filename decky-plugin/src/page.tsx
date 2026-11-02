import { ConfirmModal, DialogButton, Dropdown, Field, Focusable, Navigation, Tabs, ToggleField, showModal } from "@decky/ui";
import { ReactNode, useEffect, useState } from "react";
import {
  Conflict, Event, Profile, ProviderRow, RecentSave, Snapshot, asList, disconnect, getActivity, getHistory,
  getProfiles, getProviders, getRecent, getStatus, pull, push, resolve, restore, setProfile,
} from "./api";
import { DIM, ago, fileName, report, size, summary } from "./format";
import { AboutTab } from "./about";
import { chooseProvider, showConnect } from "./modals";
import { cancelSignIn, reopenSignIn, useSignIn } from "./signin";

export const PAGE_ROUTE = "/extra-life";
const FIRST_TAB = "providers";
let initialTab = FIRST_TAB;
export function setInitialTab(tab: string) {
  initialTab = tab;
}

/** Open the full Extra Life page (cog in the title, buttons in the panel, status bar icon). */
export function openPage(tab = FIRST_TAB) {
  setInitialTab(tab);
  Navigation.CloseSideMenus();
  Navigation.Navigate(PAGE_ROUTE);
}

function confirm(title: string, text: string, ok: string, action: () => void) {
  showModal(<ConfirmModal strTitle={title} strDescription={text} strOKButtonText={ok} onOK={action} />);
}

function Empty({ children }: { children: ReactNode }) {
  return <div style={{ ...DIM, padding: "16px 0" }}>{children}</div>;
}

function Buttons({ children }: { children: ReactNode }) {
  return <Focusable style={{ display: "flex", gap: 8 }} flow-children="horizontal">{children}</Focusable>;
}

const btn = { minWidth: 0, padding: "6px 14px", width: "auto" } as const;

function RecentTab() {
  const [rows, setRows] = useState<RecentSave[] | null>(null);
  useEffect(() => { getRecent(200).then((r) => setRows(asList(r))); }, []);
  if (!rows) return <Empty>Loading…</Empty>;
  if (!rows.length) return <Empty>Nothing synced yet.</Empty>;
  return (
    <>
      {rows.map((r) => (
        <Field key={`${r.key}/${r.rel}`} focusable label={fileName(r.rel)}
          description={`${r.name} · ${r.rel} · saved on ${r.device || "?"}` +
            (r.providers?.length ? ` · in ${r.providers.join(", ")}` : "")}>
          <div style={{ textAlign: "right", whiteSpace: "nowrap" }}>
            <div>{ago(r.modified)}</div>
            <div style={DIM}>{size(r.size)}</div>
          </div>
        </Field>
      ))}
    </>
  );
}

function useConnected(): ProviderRow[] {
  const [rows, setRows] = useState<ProviderRow[]>([]);
  useEffect(() => { getStatus().then((s) => setRows(s.providers ?? [])); }, []);
  return rows;
}

function EmulatorsTab() {
  const [rows, setRows] = useState<Profile[] | null>(null);
  const [busy, setBusy] = useState(false);
  const provs = useConnected();
  const load = () => getProfiles().then((r) => setRows(asList(r)));
  useEffect(() => { load(); }, []);
  const run = async (title: string, fn: () => Promise<any>) => {
    setBusy(true);
    try { report(title, await fn()); } finally { setBusy(false); }
  };
  if (!rows) return <Empty>Loading…</Empty>;
  return (
    <>
      {rows.map((p) => {
        const where = p.sets.find((s) => s.root && s.kind === "saves")?.root;
        return (
          <div key={p.id}>
            <ToggleField label={p.name} description={where ?? "Not found on this device"} checked={p.enabled}
              disabled={!p.available && !p.enabled}
              onChange={(v) => setProfile(p.id, v ? (p.available ? "auto" : "enable") : "disable").then(load)} />
            {p.enabled && p.available && (
              <Field label="" bottomSeparator="standard">
                <Buttons>
                  <DialogButton style={btn} disabled={busy} onClick={() => confirm(
                    `Push ${p.name}?`, "This device's saves for this emulator become the newest in every provider.",
                    "Push", () => run(`Push ${p.name}`, () => push(null, p.id)))}>Force push</DialogButton>
                  <DialogButton style={btn} disabled={busy || !provs.length} onClick={() => chooseProvider(
                    provs, `Pull ${p.name} from…`, "Its saves replace the ones here (backed up first).",
                    (pr) => confirm(`Pull ${p.name} from ${pr.name}?`,
                      `${pr.name}'s saves for this emulator replace the ones here (backed up first).`,
                      "Pull", () => run(`Pull ${p.name}`, () => pull(null, p.id, pr.id))))}>Force pull</DialogButton>
                </Buttons>
              </Field>
            )}
          </div>
        );
      })}
    </>
  );
}

function HistoryTab() {
  const provs = useConnected();
  const [prov, setProv] = useState<string | null>(null);
  const [rows, setRows] = useState<Snapshot[] | null>(null);
  const [error, setError] = useState("");
  const current = prov ?? provs[0]?.id ?? null;
  useEffect(() => {
    if (!current) return;
    setRows(null);
    setError("");
    getHistory(40, current).then((r) => {
      if (Array.isArray(r)) setRows(r);
      else { setRows([]); setError((r as any)?.error ?? r?.errors?.[0] ?? ""); }
    });
  }, [current]);
  const picker = provs.length > 1 && (
    <Field label="Provider">
      <Dropdown rgOptions={provs.map((p) => ({ data: p.id, label: p.name }))} selectedOption={current}
        onChange={(o) => setProv(o.data)} />
    </Field>
  );
  if (!provs.length) return <Empty>No provider connected.</Empty>;
  if (!rows) return <>{picker}<Empty>Loading older versions…</Empty></>;
  if (error) return <>{picker}<Empty>{error}</Empty></>;
  if (!rows.length) return <>{picker}<Empty>No older versions yet. They appear when a save is replaced or deleted.</Empty></>;
  return (
    <>
      {picker}
      {rows.map((h) => (
        <div key={h.id}>
          <div style={{ ...DIM, marginTop: 12 }}>Replaced {ago(h.time)} by a sync from {h.device}</div>
          {h.files.map((f) => (
            <Field key={`${h.id}/${f.key}/${f.rel}`} label={fileName(f.rel)} description={`${f.key} · ${size(f.size)}`}>
              <DialogButton style={btn} onClick={() => confirm(
                "Restore this version?",
                `${f.rel} from ${new Date(h.time).toLocaleString()} replaces the current one on this device and in ` +
                "every provider. The current one is kept in History and in the local backup.",
                "Restore", async () => report("Restore", await restore(h.id, f.key, f.rel, current)))}>Restore</DialogButton>
            </Field>
          ))}
        </div>
      ))}
    </>
  );
}

function ConflictsTab() {
  const [rows, setRows] = useState<Conflict[] | null>(null);
  const [busy, setBusy] = useState(false);
  const load = () => getStatus().then((s) => setRows(s.conflicts ?? []));
  useEffect(() => { load(); }, []);
  const keep = async (side: "local" | "cloud", c?: Conflict) => {
    setBusy(true);
    try {
      report(side === "local" ? "Kept this device" : "Kept the other copy",
        await resolve(side, c?.key ?? null, c?.rel ?? null, c?.provider ?? null));
    }
    finally { setBusy(false); load(); }
  };
  if (!rows) return <Empty>Loading…</Empty>;
  if (!rows.length) return <Empty>No conflicts.</Empty>;
  return (
    <>
      <div style={{ ...DIM, margin: "8px 0" }}>
        These saves changed both here and on another device since the last sync. Nothing was overwritten; pick the
        version to keep. The other one stays in History or in the local backup.
      </div>
      <Field label="All conflicts">
        <Buttons>
          <DialogButton style={btn} disabled={busy} onClick={() => keep("local")}>Keep this device</DialogButton>
          <DialogButton style={btn} disabled={busy} onClick={() => keep("cloud")}>Keep other copies</DialogButton>
        </Buttons>
      </Field>
      {rows.map((c) => (
        <Field key={`${c.key}/${c.rel}`} label={fileName(c.rel)}
          description={`${c.name} · ${c.rel} · other copy in ${c.provider_name}, from ${c.remote?.device ?? "?"} ` +
            ago(c.remote?.time)}>
          <Buttons>
            <DialogButton style={btn} disabled={busy} onClick={() => keep("local", c)}>This device</DialogButton>
            <DialogButton style={btn} disabled={busy} onClick={() => keep("cloud", c)}>{c.provider_name}</DialogButton>
          </Buttons>
        </Field>
      ))}
    </>
  );
}

const HINTS: Record<string, string> = {
  oauth: "Sign in with your account",
  folder: "SD card, USB drive or mounted share",
  ssh: "Needs SSH key login and rsync",
  rclone: "A remote set up with rclone config",
};

function providerState(p: ProviderRow): string {
  if (!p.connected) return HINTS[p.kind] ?? "";
  if (p.error) return p.error;
  const lr = p.last_run;
  const where = p.target.replace(/^rclone /, "");
  if (!lr) return `${where} · not synced yet`;
  return `${where} · ${lr.ok ? `synced ${ago(lr.finished)}: ${summary(lr)}` : `last sync failed: ${lr.errors?.[0] ?? ""}`}`;
}

export function ProvidersTab() {
  const [rows, setRows] = useState<ProviderRow[] | null>(null);
  const [busy, setBusy] = useState("");
  const signIn = useSignIn();
  const load = () => getProviders().then((r) => setRows(r.providers ?? []));
  useEffect(() => { load(); }, []);
  if (!rows) return <Empty>Loading…</Empty>;
  const connected = rows.filter((p) => p.connected);
  const off = async (p: ProviderRow) => {
    setBusy(p.id);
    try { report(`Disconnect ${p.name}`, await disconnect(p.id)); } finally { setBusy(""); load(); }
  };
  const item = (p: ProviderRow) => signIn?.provider === p.id ? (
    <Field key={p.id} label={p.name} bottomSeparator="standard"
      description={signIn.state === "starting" ? "Preparing the sign-in page…" :
        "Waiting for you to sign in and allow access in Steam's browser. If Google refuses this browser, connect " +
        `from Desktop Mode: extralife provider connect ${p.id}`}>
      <Buttons>
        <DialogButton style={btn} disabled={!signIn.url} onClick={reopenSignIn}>Open sign-in page</DialogButton>
        <DialogButton style={btn} onClick={() => cancelSignIn()}>Cancel</DialogButton>
      </Buttons>
    </Field>
  ) : (
    <Field key={p.id} label={<span>{p.connected ? "● " : ""}{p.name}</span>} description={providerState(p)}
      bottomSeparator="standard">
      {p.connected ? (
        <DialogButton style={btn} disabled={!!busy} onClick={() => confirm(
          `Disconnect ${p.name}?`,
          `Extra Life stops syncing with ${p.name}` + (p.kind === "oauth" ? " and forgets the sign-in" : "") +
          ". Saves already stored there stay where they are.", "Disconnect", () => off(p))}>
          {busy === p.id ? "…" : "Disconnect"}
        </DialogButton>
      ) : (
        <DialogButton style={btn} disabled={!!busy || !!signIn} onClick={() => showConnect(p, load)}>Connect</DialogButton>
      )}
    </Field>
  );
  return (
    <>
      <div style={{ ...DIM, margin: "8px 0" }}>
        {connected.length
          ? `Every sync keeps your saves the same in all ${connected.length} connected provider(s).`
          : "Connect at least one place for your saves. You can connect several: every sync updates all of them."}
      </div>
      {connected.map(item)}
      {rows.filter((p) => !p.connected).map(item)}
    </>
  );
}

const ACTIONS: Record<string, string> = {
  upload: "Uploaded", download: "Downloaded", remote_delete: "Deleted in cloud", local_delete: "Deleted here",
  conflict: "Conflict", restore: "Restored",
};

function ActivityTab() {
  const [rows, setRows] = useState<Event[] | null>(null);
  useEffect(() => { getActivity(150).then((r) => setRows(asList(r))); }, []);
  if (!rows) return <Empty>Loading…</Empty>;
  if (!rows.length) return <Empty>No activity yet.</Empty>;
  return (
    <>
      {rows.map((e, i) => (
        <Field key={i} focusable label={`${ACTIONS[e.action] ?? e.action}: ${fileName(e.rel)}`}
          description={`${e.name} · ${e.rel}${e.provider_name ? ` · ${e.provider_name}` : ""}` +
            (e.source ? ` · from ${e.source}` : "")}>
          <div style={{ whiteSpace: "nowrap" }}>{ago(e.time)}</div>
        </Field>
      ))}
    </>
  );
}

export function SavesPage() {
  const [tab, setTab] = useState(initialTab);
  useEffect(() => () => { initialTab = FIRST_TAB; }, []);
  return (
    <div style={{ marginTop: 40, height: "calc(100% - 40px)", background: "#0e141b" }}>
      <Tabs activeTab={tab} onShowTab={setTab} autoFocusContents tabs={[
        { id: "providers", title: "Providers", content: <Page><ProvidersTab /></Page> },
        { id: "recent", title: "Recent saves", content: <Page><RecentTab /></Page> },
        { id: "emulators", title: "Emulators", content: <Page><EmulatorsTab /></Page> },
        { id: "history", title: "History", content: <Page><HistoryTab /></Page> },
        { id: "conflicts", title: "Conflicts", content: <Page><ConflictsTab /></Page> },
        { id: "activity", title: "Activity", content: <Page><ActivityTab /></Page> },
        { id: "about", title: "About", content: <Page><AboutTab /></Page> },
      ]} />
    </div>
  );
}

function Page({ children }: { children: ReactNode }) {
  return <div style={{ padding: "0 24px 24px" }}>{children}</div>;
}
