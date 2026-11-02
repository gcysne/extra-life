// Sync indicator in Steam's Game Mode status bar, like Steam's own download/cloud icon: a heart with a small
// progress bar under it, shown only while a sync runs (it disappears a moment after reaching 100%).
// Steam has no API for this. Same technique as Sidequest's icon (sidequest docs/spikes/statusbar-icon.md): wrap the
// header component, found by a stable string in its source; on any mismatch log and do nothing.
// Other plugins (Sidequest) may wrap the same component: we never remove a wrapper that isn't ours on top, and a
// reloaded plugin reuses its existing wrapper instead of stacking a new one.
import { Focusable } from "@decky/ui";
import { useState } from "react";
import { useProgress, progressText } from "./progress";

const MARKER = "quickAccessHeader";
const TAG = "[extra-life]";

type Memo = { $$typeof: symbol; type: any };
type Hook = { active: boolean; render: () => any };
let patched: { memo: Memo; wrapper: any } | null = null;

function siblingClasses(el: HTMLElement): string[] {
  const sibs = [...(el.parentElement?.children ?? [])].filter(
    (e) => e !== el && e.getAttribute("tabindex") !== null && e.getAttribute("role") !== null,
  ) as HTMLElement[];
  if (!sibs.length) return [];
  let common = [...sibs[0].classList];
  for (const e of sibs.slice(1)) common = common.filter((c) => e.classList.contains(c));
  return common.filter((c) => c !== "Panel" && c !== "Focusable");
}

let openTarget = () => {};
export function setIconTarget(f: () => void) { openTarget = f; }

function SyncIcon() {
  const p = useProgress();
  const [extra, setExtra] = useState("");
  if (!p.visible) return null;
  const pct = Math.max(2, Math.min(100, p.percent ?? 0));
  const ref = (el: HTMLElement | null) => {
    if (!el || extra) return;
    const c = siblingClasses(el).join(" ");
    if (c) setExtra(c);
  };
  return (
    <Focusable
      ref={ref as any}
      className={`extralife-icon ${extra}`}
      onActivate={() => openTarget()}
      onClick={() => openTarget()}
      title={`Extra Life: ${progressText(p)} ${Math.round(pct)}%`}
      style={{ display: "flex", alignItems: "center", justifyContent: "center",
               cursor: "pointer", ...(extra ? {} : { height: "100%", padding: "0 8px" }) }}
    >
      {/* Fixed 18x22 box, centred like the 18x18 neighbour icons. Steam's icon classes resize any svg inside,
          so the size is set inline (inline style wins over those class rules). */}
      <div style={{ width: 18, height: 22, display: "flex", flexDirection: "column", alignItems: "center",
                    justifyContent: "space-between", flexShrink: 0 }}>
        <svg viewBox="0 0 24 21" style={{ display: "block", width: 17, height: 15, minWidth: 17, maxWidth: 17,
                                          minHeight: 15, maxHeight: 15 }}>
          <path fill={p.running || p.ok !== false ? "#dcdedf" : "#e3a35b"}
            d="M12 21l-1.7-1.6C4.2 13.9 0 10.1 0 5.9 0 2.6 2.6 0 5.9 0c1.9 0 3.7.9 4.9 2.3h2.4C14.4.9 16.2 0 18.1 0 21.4 0 24 2.6 24 5.9c0 4.2-4.2 8-10.3 13.5z" />
        </svg>
        <div style={{ width: 18, height: 3, borderRadius: 2, background: "rgba(255,255,255,0.25)", overflow: "hidden" }}>
          <div style={{ width: `${pct}%`, height: "100%", background: "#1a9fff", transition: "width 0.6s linear" }} />
        </div>
      </div>
    </Focusable>
  );
}

function findHeaderMemo(): Memo | null {
  let req: any;
  (window as any).webpackChunksteamui.push([[Symbol("extra-life")], {}, (r: any) => { req = r; }]);
  const hits: Memo[] = [];
  for (const id of Object.keys(req.m)) {
    let mod: any;
    try { mod = req(id); } catch { continue; }
    if (!mod || typeof mod !== "object") continue;
    for (const k of Object.keys(mod)) {
      let v: any;
      try { v = mod[k]; } catch { continue; }
      if (v?.$$typeof === Symbol.for("react.memo") && typeof v.type === "function" &&
          v.type.toString().includes(MARKER) && !hits.includes(v)) hits.push(v);
    }
  }
  if (hits.length !== 1) { console.warn(TAG, `header component matches: ${hits.length}, icon disabled`); return null; }
  return hits[0];
}

// Header fibers already on screen: swap their type and bump Steam's force-update counter (hook 0).
function swapLiveFibers(from: any, to: any) {
  for (const w of (window as any).SteamUIStore?.WindowStore?.SteamUIWindows ?? []) {
    const doc: Document | undefined = (w.m_BrowserWindow || w.BrowserWindow)?.document;
    const host = doc?.querySelector(".FlexGrowUniversalSearch") as any;
    if (!host) continue;
    let f = host[Object.keys(host).find((k) => k.startsWith("__reactFiber")) ?? ""];
    while (f && f.type !== from) f = f.return;
    if (!f) continue;
    f.type = to;
    if (f.alternate) f.alternate.type = to;
    const q = f.memoizedState?.queue;
    if (typeof q?.dispatch === "function" && typeof f.memoizedState.memoizedState === "number") q.dispatch((n: number) => n + 1);
  }
}

function forceUpdate(type: any) {
  swapLiveFibers(type, type);
}

export function patchStatusBar(): boolean {
  const React = (window as any).SP_REACT;
  const memo = findHeaderMemo();
  if (!memo || !React) return false;
  const render = () => <SyncIcon key="extralife-icon" />;
  // Find our wrapper from an earlier load of this plugin anywhere in the chain of wrappers.
  const existing: Hook | undefined = memo.type.__extralife;
  if (existing) {
    existing.active = true;
    existing.render = render;
    patched = { memo, wrapper: memo.type };
    forceUpdate(memo.type);
    return true;
  }
  const orig = memo.type;
  const hook: Hook = { active: true, render };
  const wrapper: any = function (this: any, props: any) {
    const ret = orig.call(this, props);
    if (!hook.active) return ret;
    try {
      if (!props?.quickAccessHeader) {
        const arr = ret?.props?.children?.props?.children;
        if (Array.isArray(arr)) {
          const grp = [...arr].reverse().find((x: any) => x?.type === React.Fragment && Array.isArray(x.props?.children));
          if (grp && !grp.props.children.some((c: any) => c?.key === "extralife-icon")) {
            grp.props.children = [hook.render(), ...grp.props.children];
          }
        }
      }
    } catch (e) { console.error(TAG, "status bar inject failed", e); }
    return ret;
  };
  wrapper.__extralife = hook;
  wrapper.toString = () => orig.toString();       // other plugins find the header by its source
  memo.type = wrapper;
  patched = { memo, wrapper };
  swapLiveFibers(orig, wrapper);
  return true;
}

export function unpatchStatusBar() {
  if (!patched) return;
  const { memo, wrapper } = patched;
  const hook: Hook = wrapper.__extralife;
  hook.active = false;           // stays in place as a pass-through; reused if the plugin loads again
  forceUpdate(memo.type);
  patched = null;
}
