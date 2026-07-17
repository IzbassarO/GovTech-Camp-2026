export type ProtectedJobMode = "prepared_replay" | "live_analysis";

function storageKey(mode: ProtectedJobMode, jobId: string): string {
  return `dalel:${mode}:job-token:${jobId}`;
}

export function rememberJobToken(
  mode: ProtectedJobMode,
  jobId: string,
  accessToken: string,
): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(storageKey(mode, jobId), accessToken);
  } catch {
    // The caller will fail closed on the protected route if storage is blocked.
  }
}

export function readJobToken(mode: ProtectedJobMode, jobId: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(storageKey(mode, jobId));
  } catch {
    return null;
  }
}

export function forgetJobToken(mode: ProtectedJobMode, jobId: string): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(storageKey(mode, jobId));
  } catch {
    // Storage may have been disabled after job creation; deletion still fails closed.
  }
}
