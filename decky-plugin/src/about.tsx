// Title bar with the cog (opens the full Extra Life page) and the About tab of that page.
import { DialogButton, Field, Focusable, ModalRoot, Navigation, showModal, staticClasses } from "@decky/ui";
import { useEffect, useState } from "react";
import { UpdateInfo, getStatus, updateCheck } from "./api";

export const REPO = "https://github.com/gcysne/extra-life";

const openUrl = (url: string) => Navigation.NavigateToExternalWeb(url);

const cogIcon = (
  <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">
    <path d="M19.14 12.94a7.07 7.07 0 0 0 .06-.94 7.07 7.07 0 0 0-.06-.94l2.03-1.58a.49.49 0 0 0 .12-.62l-1.92-3.32a.49.49 0 0 0-.59-.22l-2.39.96a7.03 7.03 0 0 0-1.62-.94l-.36-2.54a.48.48 0 0 0-.48-.4h-3.84a.48.48 0 0 0-.48.4l-.36 2.54c-.59.24-1.13.56-1.62.94l-2.39-.96a.48.48 0 0 0-.59.22L2.74 8.87a.48.48 0 0 0 .12.62l2.03 1.58a7.4 7.4 0 0 0 0 1.88l-2.03 1.58a.49.49 0 0 0-.12.62l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.49.38 1.03.7 1.62.94l.36 2.54c.05.24.25.4.48.4h3.84c.24 0 .44-.16.48-.4l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32a.49.49 0 0 0-.12-.62l-2.03-1.58zM12 15.6a3.6 3.6 0 1 1 0-7.2 3.6 3.6 0 0 1 0 7.2z" />
  </svg>
);

// Quick Access title: name on the left, cog on the right (same as Sidequest and CSS Loader).
export function TitleView({ onCog }: { onCog: () => void }) {
  return (
    <Focusable className={staticClasses.Title}
      style={{ display: "flex", alignItems: "center", width: "100%", padding: 0, boxShadow: "none" }}>
      <div style={{ marginRight: "auto" }}>Extra Life</div>
      <DialogButton style={{ height: 28, width: 40, minWidth: 0, padding: "6px 12px", display: "flex",
        alignItems: "center", justifyContent: "center" }} onClick={onCog}>
        {cogIcon}
      </DialogButton>
    </Focusable>
  );
}

const h2 = { fontWeight: "bold", fontSize: "1.3em", margin: "20px 0 6px" } as const;

/** Copy text from Steam's UI: the Clipboard API needs a focused document, the old execCommand is the fallback. */
async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch { /* fall through */ }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  } catch {
    return false;
  }
}

function UpdateModal({ info, close }: { info: UpdateInfo; close: () => void }) {
  const [copied, setCopied] = useState<"" | "ok" | "fail">("");
  const step = { margin: "6px 0" } as const;
  return (
    <ModalRoot onCancel={close}>
      <div style={{ fontSize: 22, fontWeight: 700, marginBottom: 8 }}>Update Extra Life to {info.latest}</div>
      <div style={{ ...muted, marginBottom: 12 }}>You have {info.current}. Updating keeps your providers, settings and saves.</div>
      <div style={step}>1. Switch to Desktop Mode: Steam button → Power → Switch to Desktop.</div>
      <div style={step}>2. Open <b>Konsole</b> (application menu → System → Konsole).</div>
      <div style={step}>3. Run this command, and type your password when it asks (only to update the Decky plugin):</div>
      <div style={{ fontFamily: "monospace", fontSize: 13, background: "#0b0f14", border: "1px solid #ffffff22",
                    borderRadius: 4, padding: "10px 12px", margin: "8px 0", wordBreak: "break-all", userSelect: "text" }}>
        {info.command}
      </div>
      <div style={step}>4. Switch back to Game Mode (Return to Gaming Mode icon on the desktop).</div>
      {copied === "ok" && <div style={{ color: "#59bf40", marginTop: 8 }}>Copied. Paste it in Konsole with Ctrl+Shift+V.</div>}
      {copied === "fail" && <div style={{ color: "#e3a35b", marginTop: 8 }}>Couldn't copy here: type the command in Konsole instead.</div>}
      <Focusable style={{ display: "flex", gap: 8, marginTop: 16, flexWrap: "wrap" }} flow-children="horizontal">
        <DialogButton style={btn} onClick={async () => setCopied((await copyText(info.command)) ? "ok" : "fail")}>
          Copy command
        </DialogButton>
        {info.url && <DialogButton style={btn} onClick={() => openUrl(info.url!)}>Release notes</DialogButton>}
        <DialogButton style={btn} onClick={close}>Close</DialogButton>
      </Focusable>
    </ModalRoot>
  );
}

function showUpdate(info: UpdateInfo) {
  const m = showModal(<UpdateModal info={info} close={() => m.Close()} />);
}

function UpdateRow() {
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const check = async (force: boolean) => {
    setBusy(true);
    try { setInfo(await updateCheck(force)); } catch { /* backend reloading */ } finally { setBusy(false); }
  };
  useEffect(() => { check(false); }, []);
  if (info?.newer) {
    return (
      <Field label={<span style={{ color: "#1a9fff" }}>New version available: {info.latest}</span>}
        description={`You have ${info.current}.`} bottomSeparator="none">
        <DialogButton style={btn} onClick={() => showUpdate(info)}>Update</DialogButton>
      </Field>
    );
  }
  const state = !info ? "Checking for updates…" : info.error ? `Update check: ${info.error}` : "You have the latest version.";
  return (
    <Field label="" description={state} bottomSeparator="none">
      <DialogButton style={btn} disabled={busy} onClick={() => check(true)}>{busy ? "Checking…" : "Check now"}</DialogButton>
    </Field>
  );
}
const muted = { color: "#8b929a" } as const;
const linkRow = { display: "flex", gap: 10, flexWrap: "wrap", marginTop: 12 } as const;
const btn = { width: "auto", minWidth: 0, padding: "8px 16px" } as const;

export function AboutTab() {
  const [version, setVersion] = useState("");
  const [device, setDevice] = useState("");
  useEffect(() => {
    getStatus().then((s) => { setVersion(s.version ?? ""); setDevice(s.device?.name ?? ""); }).catch(() => {});
  }, []);
  return (
    <div style={{ paddingTop: 12 }}>
      <div style={{ fontSize: "1.8em", fontWeight: "bold" }}>♥ Extra Life</div>
      <div style={muted}>{version ? `Version ${version}` : "Alpha"}{device ? ` · this device: ${device}` : ""}</div>
      <UpdateRow />
      <p>
        Keeps your emulator save games safe and the same on every device. After each play session it uploads the
        saves that changed to every provider you connected (cloud services, a card or drive, a NAS) and brings in
        the ones another device changed. Older versions are kept, and saves changed on two devices are never
        overwritten: you choose which one to keep.
      </p>
      <Focusable style={linkRow}>
        <DialogButton style={btn} onClick={() => openUrl(REPO)}>Project page</DialogButton>
        <DialogButton style={btn} onClick={() => openUrl(`${REPO}#readme`)}>User guide</DialogButton>
        <DialogButton style={btn} onClick={() => openUrl(`${REPO}/issues`)}>Report a problem</DialogButton>
      </Focusable>

      <div style={h2}>Creator</div>
      <div style={{ fontSize: "1.2em", fontWeight: "bold" }}>Gabriel Cysne</div>
      <div>
        Idealizer and lead of the project: had the idea, sets its direction and design, and tests every build on
        real hardware. Main contributor.
      </div>
      <Focusable style={linkRow}>
        <DialogButton style={btn} onClick={() => openUrl("https://www.linkedin.com/in/gcysne")}>linkedin.com/in/gcysne</DialogButton>
        <DialogButton style={btn} onClick={() => openUrl("https://github.com/gcysne")}>github.com/gcysne</DialogButton>
      </Focusable>

      <div style={h2}>Code</div>
      <div>Written by Claude (Anthropic's Claude Code), working with Gabriel Cysne.</div>
      <div style={h2}>Contributors</div>
      <div>Everyone who reports problems, adds emulator profiles, tests on new devices and sends improvements.</div>
      <Focusable style={linkRow}>
        <DialogButton style={btn} onClick={() => openUrl(`${REPO}/graphs/contributors`)}>All contributors</DialogButton>
      </Focusable>

      <div style={h2}>Built with</div>
      <div style={muted}>Decky Loader · rclone · rsync · Python</div>
      <div style={h2}>License</div>
      <div>Open source under the MIT License.</div>
      <div style={h2}>Disclaimer</div>
      <div style={muted}>
        Extra Life is a community project, not affiliated with or endorsed by Valve, Google, Dropbox, Microsoft,
        Box, pCloud or any emulator project. It copies only save data; it never downloads or shares games, BIOS,
        firmware or keys.
      </div>
    </div>
  );
}
