// Recent analyses kept on this device so they still open without a connection (FR19).
// Only results of POST requests are stored here (GET requests are cached by the service worker).

const INDEX = "mt-offline-index";
const MAX_ITEMS = 25;

function key(path: string, body: unknown): string {
  const s = path + "|" + JSON.stringify(body);
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
  return "mt-offline:" + (h >>> 0).toString(36);
}

export function remember(path: string, body: unknown, value: unknown): void {
  try {
    const k = key(path, body);
    localStorage.setItem(k, JSON.stringify(value));
    const idx: string[] = JSON.parse(localStorage.getItem(INDEX) ?? "[]").filter((x: string) => x !== k);
    idx.push(k);
    while (idx.length > MAX_ITEMS) localStorage.removeItem(idx.shift() as string);
    localStorage.setItem(INDEX, JSON.stringify(idx));
  } catch {
    /* storage full or unavailable: offline copies are a convenience only */
  }
}

export function recall<T>(path: string, body: unknown): T | null {
  try {
    const v = localStorage.getItem(key(path, body));
    return v ? (JSON.parse(v) as T) : null;
  } catch {
    return null;
  }
}

export function signalOffline(): void {
  window.dispatchEvent(new Event("mt-offline-result"));
}
