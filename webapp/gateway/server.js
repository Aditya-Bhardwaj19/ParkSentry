/**
 * ViolationProto -- Node/Express API gateway.
 *
 * Role in the stack:
 *   Browser (React) -> *this gateway* (:3000) -> Python FastAPI (:8000)
 *
 * Responsibilities (browser-facing concerns only -- the ML lives in FastAPI):
 *   1. GET /api/maptoken  -- mint a short-lived Mappls access token from the
 *      OAuth client_id/client_secret. This is done server-side ON PURPOSE so the
 *      client secret never reaches the browser; the browser only ever sees the
 *      throwaway token used in the Mappls map_sdk <script> URL.
 *   2. Proxy every other /api/* request to the Python FastAPI service.
 *   3. In production, serve the built React SPA from ../frontend/dist.
 *
 * Credentials (environment variables):
 *   MAPPLS_CLIENT_ID, MAPPLS_CLIENT_SECRET  -- OAuth pair (preferred)
 *   MAPPLS_MAP_SDK_KEY                       -- static fallback key
 */
const path = require('path');
const fs = require('fs');
const express = require('express');
const { createProxyMiddleware } = require('http-proxy-middleware');

const PORT = process.env.GATEWAY_PORT || 3000;
const API_URL = process.env.API_URL || 'http://127.0.0.1:8000';
const OAUTH_URL = 'https://outpost.mappls.com/api/security/oauth/token';

const app = express();

// --------------------------------------------------------------------------- //
// Mappls token minting (cached in-memory until ~60s before expiry)
// --------------------------------------------------------------------------- //
let tokenCache = { token: null, expiresAt: 0 };

async function mintMapplsToken() {
  const clientId = process.env.MAPPLS_CLIENT_ID;
  const clientSecret = process.env.MAPPLS_CLIENT_SECRET;
  const staticKey = process.env.MAPPLS_MAP_SDK_KEY;

  // OAuth pair -> mint a real access token.
  if (clientId && clientSecret) {
    const now = Date.now();
    if (tokenCache.token && now < tokenCache.expiresAt) {
      return { token: tokenCache.token, source: 'oauth-cached' };
    }
    const body = new URLSearchParams({
      grant_type: 'client_credentials',
      client_id: clientId,
      client_secret: clientSecret,
    });
    const resp = await fetch(OAUTH_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    });
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`Mappls OAuth ${resp.status}: ${text.slice(0, 200)}`);
    }
    const data = await resp.json();
    if (!data.access_token) {
      throw new Error('No access_token in Mappls OAuth response');
    }
    const ttlMs = ((data.expires_in || 86400) - 60) * 1000; // refresh 60s early
    tokenCache = { token: data.access_token, expiresAt: Date.now() + ttlMs };
    return { token: data.access_token, source: 'oauth' };
  }

  // Static Map SDK key fallback.
  if (staticKey) {
    return { token: staticKey, source: 'static-key' };
  }

  return { token: null, source: 'unconfigured' };
}

app.get('/api/maptoken', async (_req, res) => {
  try {
    const { token, source } = await mintMapplsToken();
    if (!token) {
      return res.status(200).json({
        configured: false,
        message:
          'Mappls credentials not set. Define MAPPLS_CLIENT_ID + MAPPLS_CLIENT_SECRET ' +
          '(or MAPPLS_MAP_SDK_KEY) in the gateway environment.',
      });
    }
    res.json({ configured: true, token, source });
  } catch (e) {
    res.status(502).json({ configured: false, error: String(e.message || e) });
  }
});

app.get('/health', (_req, res) => res.json({ status: 'ok', api: API_URL }));

// --------------------------------------------------------------------------- //
// Proxy all other /api/* calls to the Python FastAPI service.
// (Registered AFTER /api/maptoken + /health so those routes take precedence.)
//
// We mount at root with a `pathFilter` rather than `app.use('/api', ...)` so the
// full "/api/..." path is preserved and forwarded verbatim. Mounting on '/api'
// would make Express strip the prefix, and the request would hit FastAPI as
// "/summary" (404) instead of "/api/summary".
// --------------------------------------------------------------------------- //
app.use(
  createProxyMiddleware({
    pathFilter: (pathname) => pathname.startsWith('/api'),
    target: API_URL,
    changeOrigin: true,
  })
);

// --------------------------------------------------------------------------- //
// Serve the built SPA in production (no-op in dev where Vite serves it).
// --------------------------------------------------------------------------- //
const dist = path.join(__dirname, '..', 'frontend', 'dist');
if (fs.existsSync(dist)) {
  app.use(express.static(dist));
  app.get('*', (_req, res) => res.sendFile(path.join(dist, 'index.html')));
}

app.listen(PORT, () => {
  console.log(`[gateway] listening on http://localhost:${PORT}  ->  API ${API_URL}`);
  const mode = process.env.MAPPLS_CLIENT_ID
    ? 'OAuth (client_id/secret)'
    : process.env.MAPPLS_MAP_SDK_KEY
    ? 'static Map SDK key'
    : 'UNCONFIGURED (set MAPPLS_* env vars)';
  console.log(`[gateway] Mappls auth mode: ${mode}`);
});
