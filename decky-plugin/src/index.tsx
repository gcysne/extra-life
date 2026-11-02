import {
  ButtonItem, ConfirmModal, PanelSection, PanelSectionRow, ToggleField, showModal,
} from "@decky/ui";
import { definePlugin, routerHook, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import {
  RecentSave, Status, asList, gameExited, getRecent, getStatus, pull, push, resumed, setSetting, setTimer, syncNow,
} from "./api";
import { DIM, ago, fileName, report, summary } from "./format";
import { chooseProvider } from "./modals";
import { TitleView } from "./about";
import { PAGE_ROUTE, SavesPage, openPage } from "./page";
import { pokeProgress, progressText, startProgress, stopProgress, useProgress } from "./progress";
import { patchStatusBar, setIconTarget, unpatchStatusBar } from "./statusbar";

const POLL_MS = 4000;

function confirm(title: string, text: string, ok: string, action: () => void) {
  showModal(<ConfirmModal strTitle={title} strDescription={text} strOKButtonText={ok} onOK={action} />);
}


function StatusLine({ s }: { s: Status }) {
  const p = useProgress();
  const lr = s.last_run;
  if (p.visible) {
    return (
      <PanelSectionRow>
        {/* Own layout: Decky's ProgressBarWithInfo puts the text beside the bar and runs off the panel. */}
        <div style={{ width: "100%", minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, minWidth: 0 }}>
            <div style={{ flex: 1, minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {p.running ? progressText(p) : "Done"}
            </div>
            <div style={{ flexShrink: 0, fontVariantNumeric: "tabular-nums" }}>{Math.round(p.percent ?? 0)}%</div>
          </div>
          <div style={{ height: 6, borderRadius: 3, background: "rgba(255,255,255,0.15)", overflow: "hidden", margin: "6px 0 4px" }}>
            <div style={{ width: `${Math.max(1, Math.min(100, p.percent ?? 0))}%`, height: "100%", background: "#1a9fff",
                          transition: "width 0.6s linear" }} />
          </div>
          {(p.providers ?? 1) > 1 && (
            <div style={DIM}>Provider {(p.provider_index ?? 0) + 1} of {p.providers}</div>
          )}
        </div>
      </PanelSectionRow>
    );
  }
  let text = "Never synced";
  if (s.running) text = "Syncing…";
  else if (lr) text = lr.ok ? `Synced ${ago(lr.finished)}: ${summary(lr)}` : `Last sync failed ${ago(lr.finished)}`;
  return (
    <PanelSectionRow>
      <div>
        <div>{text}</div>
        {lr && !lr.ok && !s.running && <div style={{ ...DIM, color: "#e3a35b" }}>{lr.errors?.[0]}</div>}
        {lr?.skipped?.length ? <div style={DIM}>Skipped while running: {lr.skipped.map((x) => x.key).join(", ")}</div> : null}
      </div>
    </PanelSectionRow>
  );
}

function ProvidersSection({ s }: { s: Status }) {
  const provs = s.providers ?? [];
  return (
    <PanelSection title="Providers">
      {provs.map((p) => {
        const lr = p.last_run;
        const bad = !!p.error || (lr && !lr.ok);
        return (
          <PanelSectionRow key={p.id}>
            <div>
              <div><span style={{ color: bad ? "#e3a35b" : "#59bf40" }}>●</span> {p.name}</div>
              <div style={DIM}>{p.error ?? (lr ? (lr.ok ? `synced ${ago(lr.finished)}` : lr.errors?.[0]) : "not synced yet")}</div>
            </div>
          </PanelSectionRow>
        );
      })}
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => openPage("providers")}>Manage providers</ButtonItem>
      </PanelSectionRow>
    </PanelSection>
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
  if (s.not_installed) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <div>Extra Life isn't installed. In Desktop Mode, run <code>install.sh</code>.</div>
        </PanelSectionRow>
      </PanelSection>
    );
  }
  if (!s.configured) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <div>Choose where your saves go: a cloud service, a folder on a card or drive, or a NAS.</div>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => openPage("providers")}>Connect a provider</ButtonItem>
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
            if (!r.ok) toaster.toast({ title: "Extra Life", body: r.errors?.[0] ?? "Couldn't start", critical: true });
            setTimeout(pokeProgress, 500);
            refresh();
          }}>Sync now</ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={disabled} onClick={() => confirm(
            "Force push?",
            "Every save on this device that differs from a provider is uploaded and becomes the newest version " +
            "in every provider. Their previous versions are kept in History.",
            "Push", () => act("Push", () => push(null, null)))}>Force push (this device → providers)</ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={disabled} onClick={() => chooseProvider(
            s.providers ?? [], "Pull from…", "Pick the provider whose saves this device should take.",
            (p) => confirm(
              `Force pull from ${p.name}?`,
              `Every save in ${p.name} that differs from this device is downloaded over the local one. Replaced ` +
              "local files are backed up first. Close any running game before pulling.",
              "Pull", () => act("Pull", () => pull(null, null, p.id))))}>Force pull (provider → this device)</ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      <ProvidersSection s={s} />
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
          <ButtonItem layout="below" onClick={() => openPage("recent")}>Browse saves and history</ButtonItem>
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
  startProgress();
  setIconTarget(() => openPage("activity"));
  try { patchStatusBar(); } catch (e) { console.error("[extra-life] status bar patch failed", e); }
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
    titleView: <TitleView onCog={() => openPage()} />,
    content: <Content />,
    icon: <span style={{ fontWeight: 700 }}>{"♥"}</span>,
    onDismount() {
      try { unpatchStatusBar(); } catch (e) { console.error("[extra-life] unpatch failed", e); }
      stopProgress();
      lifetime?.unregister();
      resume?.unregister();
      routerHook.removeRoute(PAGE_ROUTE);
    },
  };
});
