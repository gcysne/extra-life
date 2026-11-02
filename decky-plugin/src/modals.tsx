import { DialogButton, Focusable, ModalRoot, Spinner, TextField, showModal } from "@decky/ui";
import { openFilePicker, toaster } from "@decky/api";
import { ReactNode, useEffect, useState } from "react";
import { ProviderRow, Result, Volume, connect, getProviders, getVolumes } from "./api";
import { DIM, size } from "./format";
import { startSignIn } from "./signin";

const FOLDER_PICKER = 1;   // FileSelectionType.FOLDER (a const enum, not importable at runtime)
const btn = { minWidth: 0, padding: "6px 14px", width: "auto" } as const;

function Title({ children }: { children: ReactNode }) {
  return <div style={{ fontSize: 22, fontWeight: 700, marginBottom: 12 }}>{children}</div>;
}

function ErrorLine({ text }: { text?: string }) {
  return text ? <div style={{ color: "#e3a35b", margin: "8px 0" }}>{text}</div> : null;
}

/** Pick one of the connected providers (e.g. for a force pull); shown only when there are several. */
export function chooseProvider(providers: ProviderRow[], title: string, text: string, onPick: (p: ProviderRow) => void) {
  const connected = providers.filter((p) => p.connected);
  if (connected.length === 1) { onPick(connected[0]); return; }
  const m = showModal(
    <ModalRoot onCancel={() => m.Close()}>
      <Title>{title}</Title>
      <div style={{ ...DIM, fontSize: 14, marginBottom: 12 }}>{text}</div>
      <Focusable style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {connected.map((p) => (
          <DialogButton key={p.id} onClick={() => { m.Close(); onPick(p); }}>{p.name}</DialogButton>
        ))}
      </Focusable>
    </ModalRoot>,
  );
}

function done(r: Result & { target?: string }, name: string, close: () => void, onDone: () => void): string {
  if (r.ok) {
    toaster.toast({ title: "Extra Life", body: `${name} connected. The next sync includes it.` });
    close();
    onDone();
    return "";
  }
  return r.errors?.[0] ?? "Couldn't connect";
}

// ---------- folder on an SD card or USB drive ----------

function FolderModal({ p, close, onDone }: { p: ProviderRow; close: () => void; onDone: () => void }) {
  const [vols, setVols] = useState<Volume[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { getVolumes().then(setVols); }, []);
  const use = async (path: string) => {
    setBusy(true);
    setError("");
    try { setError(done(await connect(p.id, "folder", { path }), p.name, close, onDone)); } finally { setBusy(false); }
  };
  const pick = async () => {
    try {
      const r = await openFilePicker(FOLDER_PICKER as any, vols?.[0]?.path ?? "/run/media", false, true);
      if (r?.path) use(r.path);
    } catch { /* cancelled */ }
  };
  return (
    <ModalRoot onCancel={close}>
      <Title>Sync to a folder</Title>
      <div style={{ ...DIM, fontSize: 14, marginBottom: 12 }}>
        Saves go into an <b>ExtraLife</b> folder on the drive. A drive you can unplug (or another card) also
        protects you if the card with your games fails.
      </div>
      {!vols && <Spinner style={{ height: 20 }} />}
      <Focusable style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {vols?.filter((v) => v.writable).map((v) => (
          <DialogButton key={v.path} disabled={busy} onClick={() => use(`${v.path}/ExtraLife`)}>
            {v.name} <span style={DIM}>· {size(v.free)} free · {v.path}/ExtraLife</span>
          </DialogButton>
        ))}
        <DialogButton disabled={busy} onClick={pick}>Choose another folder…</DialogButton>
      </Focusable>
      <ErrorLine text={error} />
    </ModalRoot>
  );
}

// ---------- NAS or computer over SSH ----------

function SshModal({ p, close, onDone }: { p: ProviderRow; close: () => void; onDone: () => void }) {
  const [host, setHost] = useState("");
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const go = async () => {
    setBusy(true);
    setError("");
    try { setError(done(await connect(p.id, "ssh", { host, path }), p.name, close, onDone)); } finally { setBusy(false); }
  };
  return (
    <ModalRoot onCancel={close}>
      <Title>Sync to a NAS or computer (SSH)</Title>
      <div style={{ ...DIM, fontSize: 14, marginBottom: 12 }}>
        Needs SSH key login (no password prompt) and rsync on the other machine.
      </div>
      <TextField label="Host" description="As in `ssh HOST`, e.g. nas or user@192.168.1.10" value={host}
        onChange={(e) => setHost(e.target.value)} />
      <TextField label="Folder on the host" description="e.g. /shares/saves/ExtraLife" value={path}
        onChange={(e) => setPath(e.target.value)} />
      <ErrorLine text={error} />
      <Focusable style={{ display: "flex", gap: 8, marginTop: 16 }} flow-children="horizontal">
        <DialogButton style={btn} disabled={busy || !host || !path} onClick={go}>{busy ? "Testing…" : "Connect"}</DialogButton>
        <DialogButton style={btn} onClick={close}>Cancel</DialogButton>
      </Focusable>
    </ModalRoot>
  );
}

// ---------- a remote the user set up with `rclone config` ----------

function RcloneModal({ p, close, onDone }: { p: ProviderRow; close: () => void; onDone: () => void }) {
  const [remotes, setRemotes] = useState<string[] | null>(null);
  const [folder, setFolder] = useState("ExtraLife");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { getProviders().then((r) => setRemotes(r.rclone_remotes ?? [])); }, []);
  const use = async (remote: string) => {
    setBusy(true);
    setError("");
    try { setError(done(await connect(p.id, "rclone", { remote, folder }), p.name, close, onDone)); } finally { setBusy(false); }
  };
  return (
    <ModalRoot onCancel={close}>
      <Title>Other rclone remote</Title>
      <div style={{ ...DIM, fontSize: 14, marginBottom: 12 }}>
        For services set up in Desktop Mode with <code>rclone config</code> (S3, WebDAV/Nextcloud, Mega, SFTP…).
      </div>
      {!remotes && <Spinner style={{ height: 20 }} />}
      {remotes?.length === 0 && <div>No rclone remotes found. Set one up in Desktop Mode first.</div>}
      {!!remotes?.length && (
        <>
          <TextField label="Folder in it" value={folder} onChange={(e) => setFolder(e.target.value)} />
          <Focusable style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
            {remotes.map((r) => <DialogButton key={r} disabled={busy || !folder} onClick={() => use(r)}>{r}</DialogButton>)}
          </Focusable>
        </>
      )}
      <ErrorLine text={error} />
    </ModalRoot>
  );
}

export function showConnect(p: ProviderRow, onDone: () => void) {
  if (p.kind === "oauth") { startSignIn(p, onDone); return; }
  const Body = { folder: FolderModal, ssh: SshModal, rclone: RcloneModal }[p.kind];
  if (!Body) return;
  const m = showModal(<Body p={p} close={() => m.Close()} onDone={onDone} />);
}
