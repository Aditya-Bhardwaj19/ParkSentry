// Loads the Mappls Web JS (vector v3.0) SDK on demand.
//
// The access token is fetched from the gateway (/api/maptoken) so the OAuth
// client secret never reaches the browser. The token is embedded in the SDK
// script URL, then we poll for the global the SDK installs (`Mappls`, or
// `mappls` on some builds). Resolves to that global; rejects with a readable
// message the UI can surface (e.g. "credentials not configured").

let sdkPromise = null;

export function mapplsGlobal() {
  return window.Mappls || window.mappls || null;
}

export function loadMappls() {
  const existing = mapplsGlobal();
  if (existing && existing.Map) return Promise.resolve(existing);
  if (sdkPromise) return sdkPromise;

  sdkPromise = (async () => {
    const res = await fetch('/api/maptoken');
    const data = await res.json();
    if (!data.configured || !data.token) {
      throw new Error(
        data.message || data.error || 'Mappls credentials are not configured.'
      );
    }
    const url = `https://apis.mappls.com/advancedmaps/api/${data.token}/map_sdk?v=3.0&layer=vector`;
    await injectScript(url);
    await waitFor(() => mapplsGlobal() && mapplsGlobal().Map, 12000);
    return mapplsGlobal();
  })().catch((e) => {
    sdkPromise = null; // allow a later retry (e.g. after keys are set)
    throw e;
  });

  return sdkPromise;
}

function injectScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.async = true;
    s.defer = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error('Failed to load the Mappls SDK script.'));
    document.head.appendChild(s);
  });
}

function waitFor(cond, timeoutMs) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    (function check() {
      if (cond()) return resolve();
      if (Date.now() - start > timeoutMs)
        return reject(new Error('Mappls SDK did not initialise (timeout).'));
      setTimeout(check, 150);
    })();
  });
}
