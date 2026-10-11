/**
 * Session-scoped cache for the scan verification block.
 *
 * POST /scans and POST /scans/<id>/photos already return `verification`, but
 * older hub builds omit it on GET /scans/<id>. Remembering the block from the
 * scan responses keeps the camera → verify flow complete either way; a fresh
 * direct URL still relies on the hub returning it (GET).
 */
const key = (scanId) => `medcheck.verification.${scanId}`;

export function rememberVerification(scan) {
  if (!scan?.id || !scan.verification) return;
  try {
    sessionStorage.setItem(key(scan.id), JSON.stringify(scan.verification));
  } catch {
    /* private mode or storage full — the hub GET is the source of truth */
  }
}

export function cachedVerification(scanId) {
  try {
    const raw = sessionStorage.getItem(key(scanId));
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}
