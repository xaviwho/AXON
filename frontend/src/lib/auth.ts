// Tiny JWT helper. Single hardcoded admin user for the MVP — production
// swaps in the university SSO per CLAUDE.md.

const KEY = "axon.jwt";

export function getToken(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(KEY, token);
  } catch {
    /* ignore — incognito etc. */
  }
}

export function clearToken(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

export function isAuthed(): boolean {
  return !!getToken();
}
