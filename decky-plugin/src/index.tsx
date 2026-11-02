import {
  ButtonItem, ConfirmModal, Navigation, PanelSection, PanelSectionRow, ToggleField, showModal,
} from "@decky/ui";
import { definePlugin, routerHook, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import {
  RecentSave, Status, asList, gameExited, getRecent, getStatus, pull, push, resumed, setSetting, setTimer, syncNow,
} from "./api";
import { DIM, ago, fileName, report, summary } from "./format";
import { PAGE_ROUTE, SavesPage, setInitialTab } from "./page";

const POLL_MS = 4000;

function confirm(title: string, text: string, ok: string, action: () => void) {
  showModal(<ConfirmModal strTitle={title} strDescription={text} strOKButtonText={ok} onOK={action} />);
}

function openPage(tab = "recent") {
  setInitialTab(tab);
  Navigation.CloseSideMenus();
  Navigation.Navigate(PAGE_ROUTE);
}

function StatusLine({ s }: { s: Status }) {
  const lr = s.last_run;
  let text = "Never synced";
  if (s.running) text = "Syncing…";
  else if (lr) text = lr.ok ? `Synced ${ago(lr.finished)}: ${summary(lr)}` : `Last sync failed ${ago(lr.finished)}`;
  return (
    <PanelSectionRow>
      <div>
        <div>{text}</div>
        {lr && !lr.ok && !s.running && <div style={{ ...DIM, color: "#e3a35b" }}>{lr.errors?.[0]}</div>}
        {lr?.skipped?.length ? <div style={DIM}>Skipped while running: {lr.skipped.map((x) => x.key).join(", ")}</div> : null}
        <div style={DIM}>{s.remote || s.remote_error}</div>
      </div>
    </PanelSectionRow>
  );
}

function Content() {
  const [s, setS] = useState<Status | null>(null);
  const [recent, setRecent] = useState<RecentSave[]>([]);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    try {
      setS(await getStatus());
      setRecent(asList(await getRecent(5)));
    } catch (e) {
      console.error("[extra-life] status failed", e);
    }
  };

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, POLL_MS);
    return () => clearInterval(t);
  }, []);

  const act = async (title: string, fn: () => Promise<any>) => {
    setBusy(true);
    try {
      report(title, await fn());
    } finally {
      setBusy(false);
      refresh();
    }
  };

  if (!s) return <PanelSection><PanelSectionRow><div>Loading…</div></PanelSectionRow></PanelSection>;
  if (s.not_installed || !s.configured) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <div>
            {s.not_installed ? "Extra Life isn't installed." : "Extra Life isn't set up yet."} In Desktop Mode, run{" "}
            <code>{s.not_installed ? "install.sh" : "extralife setup"}</code> to choose where your saves go.
          </div>
        </PanelSectionRow>
      </PanelSection>
    );
  }
  const disabled = busy || !!s.running;
  const conflicts = s.conflicts ?? [];
  return (
    <>
      <PanelSection>
        <StatusLine s={s} />
        {conflicts.length > 0 && (
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => openPage("conflicts")}>
              {`⚠ ${conflicts.length} conflict(s): review`}
            </ButtonItem>
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={disabled} onClick={async () => {
            const r = await syncNow();
            toaster.toast({ title: "Extra Life", body: r.ok ? "Sync started" : r.errors?.[0] ?? "Couldn't start", critical: !r.ok });
            refresh();
          }}>Sync now</ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={disabled} onClick={() => confirm(
            "Force push?",
            "Every save on this device that differs from the cloud is uploaded and becomes the newest version. " +
            "The cloud's previous versions are kept in History.",
            "Push", () => act("Push", () => push(null, null)))}>Force push (this device → cloud)</ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={disabled} onClick={() => confirm(
            "Force pull?",
            "Every save in the cloud that differs from this device is downloaded over the local one. Replaced " +
            "local files are backed up first. Close any running game before pulling.",
            "Pull", () => act("Pull", () => pull(null, null)))}>Force pull (cloud → this device)</ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Recently saved">
        {recent.length === 0 && <PanelSectionRow><div style={DIM}>Nothing synced yet.</div></PanelSectionRow>}
        {recent.map((r) => (
          <PanelSectionRow key={`${r.key}/${r.rel}`}>
            <div style={{ overflow: "hidden" }}>
              <div style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{fileName(r.rel)}</div>
              <div style={DIM}>{r.name} · {ago(r.modified)} · {r.device}</div>
            </div>
          </PanelSectionRow>
        ))}
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => openPage()}>Browse saves and history</ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Settings">
        <PanelSectionRow>
          <ToggleField label="Sync when a game closes" checked={!!s.settings?.on_game_exit}
            onChange={(v) => setSetting("sync.on_game_exit", v).then(refresh)} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField label="Sync every 30 minutes" description="Also syncs a few minutes after boot"
            checked={!!s.timer_enabled} onChange={(v) => setTimer(v).then(refresh)} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField label="Include save states" description="Larger, and tied to the emulator version"
            checked={!!s.settings?.include_states} onChange={(v) => setSetting("sync.include_states", v).then(refresh)} />
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={DIM}>Extra Life {s.version} · {s.device?.name}</div>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

type Unregisterable = { unregister: () => void } | undefined;

/** Steam renames its client API between versions: register through the first name that exists, never throw. */
function hook(label: string, names: [string, string][], cb: (...args: any[]) => void): Unregisterable {
  for (const [ns, fn] of names) {
    const f = (SteamClient as any)?.[ns]?.[fn];
    if (typeof f !== "function") continue;
    try {
      return f.call((SteamClient as any)[ns], cb);
    } catch (e) {
      console.error(`[extra-life] ${ns}.${fn} failed`, e);
    }
  }
  console.warn(`[extra-life] no Steam hook for ${label} on this Steam version`);
  return undefined;
}

const logErr = (e: unknown) => console.error("[extra-life]", e);

export default definePlugin(() => {
  routerHook.addRoute(PAGE_ROUTE, () => <SavesPage />, { exact: true });
  // Push saves when a game closes; the service waits for the emulator to exit before it reads anything.
  const lifetime = hook("game exit", [["GameSessions", "RegisterForAppLifetimeNotifications"]], (n: any) => {
    if (n && !n.bRunning) gameExited(n.unAppID).catch(logErr);
  });
  // Pull what other devices saved while this one slept.
  let lastResume = 0;
  const resume = hook("resume", [["System", "RegisterForOnResumeFromSuspend"],
    ["User", "RegisterForResumeSuspendedGamesProgress"]], () => {
    if (Date.now() - lastResume < 60_000) return;   // the progress hook fires several times per wake
    lastResume = Date.now();
    resumed().catch(logErr);
  });

  return {
    name: "Extra Life",
    titleView: <div style={{ fontWeight: 700 }}>Extra Life</div>,
    content: <Content />,
    icon: <span style={{ fontWeight: 700 }}>{"♥"}</span>,
    onDismount() {
      lifetime?.unregister();
      resume?.unregister();
      routerHook.removeRoute(PAGE_ROUTE);
    },
  };
});
