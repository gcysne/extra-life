import { ConfirmModal, DialogButton, Field, Focusable, Tabs, ToggleField, showModal } from "@decky/ui";
import { ReactNode, useEffect, useState } from "react";
import {
  Conflict, Event, Profile, RecentSave, Snapshot, asList, getActivity, getHistory, getProfiles, getRecent, getStatus,
  pull, push, resolve, restore, setProfile,
} from "./api";
import { DIM, ago, fileName, report, size } from "./format";

export const PAGE_ROUTE = "/extra-life";
let initialTab = "recent";
export function setInitialTab(tab: string) {
  initialTab = tab;
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
          description={`${r.name} · ${r.rel} · saved on ${r.device || "?"}`}>
          <div style={{ textAlign: "right", whiteSpace: "nowrap" }}>
            <div>{ago(r.modified)}</div>
            <div style={DIM}>{size(r.size)}</div>
          </div>
        </Field>
      ))}
    </>
  );
}

function EmulatorsTab() {
  const [rows, setRows] = useState<Profile[] | null>(null);
  const [busy, setBusy] = useState(false);
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
                    `Push ${p.name}?`, "This device's saves for this emulator become the newest in the cloud.",
                    "Push", () => run(`Push ${p.name}`, () => push(null, p.id)))}>Force push</DialogButton>
                  <DialogButton style={btn} disabled={busy} onClick={() => confirm(
                    `Pull ${p.name}?`, "The cloud's saves for this emulator replace the ones here (backed up first).",
                    "Pull", () => run(`Pull ${p.name}`, () => pull(null, p.id)))}>Force pull</DialogButton>
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
  const [rows, setRows] = useState<Snapshot[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    getHistory(40).then((r) => {
      if (Array.isArray(r)) setRows(r);
      else { setRows([]); setError((r as any)?.error ?? r?.errors?.[0] ?? ""); }
    });
  }, []);
  if (!rows) return <Empty>Loading older versions from the cloud…</Empty>;
  if (error) return <Empty>{error}</Empty>;
  if (!rows.length) return <Empty>No older versions yet. They appear when a save is replaced or deleted.</Empty>;
  return (
    <>
      {rows.map((h) => (
        <div key={h.id}>
          <div style={{ ...DIM, marginTop: 12 }}>Replaced {ago(h.time)} by a sync from {h.device}</div>
          {h.files.map((f) => (
            <Field key={`${h.id}/${f.key}/${f.rel}`} label={fileName(f.rel)} description={`${f.key} · ${size(f.size)}`}>
              <DialogButton style={btn} onClick={() => confirm(
                "Restore this version?",
                `${f.rel} from ${new Date(h.time).toLocaleString()} replaces the current one on this device and in ` +
                "the cloud. The current one is kept in History and in the local backup.",
                "Restore", async () => report("Restore", await restore(h.id, f.key, f.rel)))}>Restore</DialogButton>
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
    try { report(side === "local" ? "Kept this device" : "Kept the cloud", await resolve(side, c?.key ?? null, c?.rel ?? null)); }
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
          <DialogButton style={btn} disabled={busy} onClick={() => keep("cloud")}>Keep cloud</DialogButton>
        </Buttons>
      </Field>
      {rows.map((c) => (
        <Field key={`${c.key}/${c.rel}`} label={fileName(c.rel)}
          description={`${c.name} · ${c.rel} · other copy from ${c.remote?.device ?? "?"} ${ago(c.remote?.time)}`}>
          <Buttons>
            <DialogButton style={btn} disabled={busy} onClick={() => keep("local", c)}>This device</DialogButton>
            <DialogButton style={btn} disabled={busy} onClick={() => keep("cloud", c)}>Cloud</DialogButton>
          </Buttons>
        </Field>
      ))}
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
          description={`${e.name} · ${e.rel}${e.source ? ` · from ${e.source}` : ""}`}>
          <div style={{ whiteSpace: "nowrap" }}>{ago(e.time)}</div>
        </Field>
      ))}
    </>
  );
}

export function SavesPage() {
  const [tab, setTab] = useState(initialTab);
  useEffect(() => () => { initialTab = "recent"; }, []);
  return (
    <div style={{ marginTop: 40, height: "calc(100% - 40px)", background: "#0e141b" }}>
      <Tabs activeTab={tab} onShowTab={setTab} autoFocusContents tabs={[
        { id: "recent", title: "Recent saves", content: <Page><RecentTab /></Page> },
        { id: "emulators", title: "Emulators", content: <Page><EmulatorsTab /></Page> },
        { id: "history", title: "History", content: <Page><HistoryTab /></Page> },
        { id: "conflicts", title: "Conflicts", content: <Page><ConflictsTab /></Page> },
        { id: "activity", title: "Activity", content: <Page><ActivityTab /></Page> },
      ]} />
    </div>
  );
}

function Page({ children }: { children: ReactNode }) {
  return <div style={{ padding: "0 24px 24px" }}>{children}</div>;
}
