import { toaster } from "@decky/api";
import type { Result } from "./api";

export function ago(iso?: string): string {
  if (!iso) return "never";
  const t = Date.parse(iso);
  if (isNaN(t)) return iso;
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)} d ago`;
  return new Date(t).toLocaleDateString();
}

export function size(n?: number): string {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/** Last part of a save path, which is usually the game's name. */
export function fileName(rel: string): string {
  const parts = rel.split("/");
  return parts[parts.length - 1] || rel;
}

export function summary(r: Result): string {
  const s = r.summary ?? {};
  const bits = [];
  if (s.uploaded) bits.push(`${s.uploaded} up`);
  if (s.downloaded) bits.push(`${s.downloaded} down`);
  if (s.conflicts) bits.push(`${s.conflicts} conflict(s)`);
  return bits.length ? bits.join(", ") : "everything in sync";
}

export function report(title: string, r: Result) {
  const reports = r.reports ?? [r];
  const errors = reports.flatMap((x) => x.errors ?? []);
  if (errors.length) {
    toaster.toast({ title: `Extra Life: ${title} failed`, body: errors[0], critical: true });
  } else {
    toaster.toast({ title: "Extra Life", body: `${title}: ${summary(reports[reports.length - 1] ?? r)}` });
  }
}

export const DIM = { fontSize: 12, color: "#8b929a" } as const;
