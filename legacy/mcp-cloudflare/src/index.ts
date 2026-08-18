import { DurableObject } from "cloudflare:workers";
import { McpServer } from "@modelcontextprotocol/server";
import { createMcpHandler } from "agents/mcp/server";
import { z } from "zod";

export interface Env {
  CAJA_STATE: DurableObjectNamespace<CajaState>;
  CHATGPT_TOKEN?: string;
  CLAUDE_TOKEN?: string;
  HUMAN_TOKEN?: string;
  OAUTH_SIGNING_KEY?: string;
}

type Actor = "chatgpt" | "claude" | "human";
type EventKind = "proposal" | "challenge" | "status_change" | "evidence";
type Status = "candidate" | "disputed" | "conditional" | "consensus" | "rejected" | "superseded" | "unresolved";

const ACTORS: Actor[] = ["chatgpt", "claude", "human"];
const STATUSES: Status[] = ["candidate", "disputed", "conditional", "consensus", "rejected", "superseded", "unresolved"];

function actorFromToken(request: Request, env: Env): Actor | null {
  const value = request.headers.get("authorization");
  if (!value?.startsWith("Bearer ")) return null;
  const token = value.slice("Bearer ".length);
  if (env.CHATGPT_TOKEN && token === env.CHATGPT_TOKEN) return "chatgpt";
  if (env.CLAUDE_TOKEN && token === env.CLAUDE_TOKEN) return "claude";
  if (env.HUMAN_TOKEN && token === env.HUMAN_TOKEN) return "human";
  return null;
}

function authError(url: URL): Response {
  return new Response("Unauthorized", { status: 401, headers: { "WWW-Authenticate": `Bearer resource_metadata="${url.origin}/.well-known/oauth-protected-resource"` } });
}

function state(env: Env): DurableObjectStub<CajaState> {
  return env.CAJA_STATE.get(env.CAJA_STATE.idFromName("default-workspace"));
}

function text(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

function createServer(env: Env, actor: Actor) {
  const server = new McpServer({ name: "La Caja", version: "0.2.0" });
  server.registerTool("get_state", { description: "Return the complete research state and immutable deliberation history." }, async () => ({ content: [{ type: "text", text: text(await state(env).execute({ op: "get_state" })) }] }));
  server.registerTool("get_entity", { description: "Return one entity and its complete deliberation history.", inputSchema: { entity_id: z.string() } }, async ({ entity_id }) => ({ content: [{ type: "text", text: text(await state(env).execute({ op: "get_entity", entity_id })) }] }));
  server.registerTool("search_context", { description: "Search entity metadata and deliberation event content.", inputSchema: { query: z.string(), limit: z.number().int().min(1).max(100).optional() } }, async ({ query, limit }) => ({ content: [{ type: "text", text: text(await state(env).execute({ op: "search_context", query, limit: limit ?? 20 })) }] }));
  server.registerTool("propose", { description: "Create a candidate proposal and preserve its originating argument.", inputSchema: { title: z.string(), content: z.string(), entity_type: z.string().optional() } }, async ({ title, content, entity_type }) => ({ content: [{ type: "text", text: text(await state(env).execute({ op: "propose", title, content, entity_type: entity_type ?? "proposal", actor })) }] }));
  server.registerTool("challenge", { description: "Record an adversarial objection without deleting prior reasoning.", inputSchema: { entity_id: z.string(), content: z.string(), targets: z.array(z.string()).optional() } }, async ({ entity_id, content, targets }) => ({ content: [{ type: "text", text: text(await state(env).execute({ op: "challenge", entity_id, content, targets: targets ?? [], actor })) }] }));
  server.registerTool("update_entity", { description: "Change an entity status while preserving the reason as an immutable event.", inputSchema: { entity_id: z.string(), status: z.enum(STATUSES), content: z.string() } }, async ({ entity_id, status, content }) => ({ content: [{ type: "text", text: text(await state(env).execute({ op: "update_entity", entity_id, status, content, actor })) }] }));
  server.registerTool("publish_evidence", { description: "Attach externally researched evidence to an entity.", inputSchema: { entity_id: z.string(), source: z.string(), claim: z.string(), notes: z.string().optional() } }, async ({ entity_id, source, claim, notes }) => ({ content: [{ type: "text", text: text(await state(env).execute({ op: "publish_evidence", entity_id, source, claim, notes: notes ?? "", actor })) }] }));
  return server;
}

// ---------------------------------------------------------------------------
// OAuth handshake wrapper (single-tenant)
//
// This is NOT a general-purpose OAuth authorization server: there is exactly
// one resource owner (Miguel). It exists only because ChatGPT's custom
// connector UI requires an OAuth dance before it will call an MCP server --
// the existing static-bearer auth (actorFromToken/authError below) keeps
// working unchanged for Claude and direct human use.
//
// Flow: ChatGPT registers a client (/register), sends Miguel to /authorize,
// which gates on his HUMAN_TOKEN as an approval password. On approval it
// issues a stateless, HMAC-signed authorization code (no KV/DB -- verified
// on /token via the same signing key). /token then simply hands back the
// existing CHATGPT_TOKEN as the access_token, so every later call to /mcp
// flows through the unmodified actorFromToken() check below.
// ---------------------------------------------------------------------------

interface AuthCodePayload {
  client_id: string;
  redirect_uri: string;
  code_challenge: string;
  exp: number;
}

function base64url(bytes: Uint8Array): string {
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function base64urlDecode(str: string): Uint8Array {
  const padded = str.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((str.length + 3) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function hmacSign(key: string, data: string): Promise<string> {
  const cryptoKey = await crypto.subtle.importKey("raw", new TextEncoder().encode(key), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", cryptoKey, new TextEncoder().encode(data));
  return base64url(new Uint8Array(sig));
}

async function sha256base64url(input: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(input));
  return base64url(new Uint8Array(digest));
}

async function signAuthCode(payload: AuthCodePayload, signingKey: string): Promise<string> {
  const body = base64url(new TextEncoder().encode(JSON.stringify(payload)));
  const sig = await hmacSign(signingKey, body);
  return `${body}.${sig}`;
}

async function verifyAuthCode(code: string, signingKey: string): Promise<AuthCodePayload | null> {
  const parts = code.split(".");
  if (parts.length !== 2) return null;
  const [body, sig] = parts;
  const expected = await hmacSign(signingKey, body);
  if (expected !== sig) return null;
  try {
    const payload = JSON.parse(new TextDecoder().decode(base64urlDecode(body))) as AuthCodePayload;
    if (typeof payload.exp !== "number" || Date.now() > payload.exp) return null;
    if (typeof payload.client_id !== "string" || typeof payload.redirect_uri !== "string" || typeof payload.code_challenge !== "string") return null;
    return payload;
  } catch {
    return null;
  }
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

function jsonResponse(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json" } });
}

function oauthAuthServerMetadata(origin: string) {
  return {
    issuer: origin,
    authorization_endpoint: `${origin}/authorize`,
    token_endpoint: `${origin}/token`,
    registration_endpoint: `${origin}/register`,
    response_types_supported: ["code"],
    grant_types_supported: ["authorization_code"],
    code_challenge_methods_supported: ["S256"],
    token_endpoint_auth_methods_supported: ["none"],
  };
}

function oauthProtectedResourceMetadata(origin: string) {
  return {
    resource: `${origin}/mcp`,
    authorization_servers: [origin],
  };
}

async function handleRegister(request: Request): Promise<Response> {
  const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
  const redirectUris = Array.isArray(body.redirect_uris) ? body.redirect_uris.filter((u): u is string => typeof u === "string") : [];
  return jsonResponse(
    {
      client_id: crypto.randomUUID(),
      client_name: typeof body.client_name === "string" ? body.client_name : "MCP Client",
      redirect_uris: redirectUris,
      token_endpoint_auth_method: "none",
      grant_types: ["authorization_code"],
      response_types: ["code"],
    },
    201,
  );
}

interface AuthorizeParams {
  client_id: string;
  redirect_uri: string;
  state: string;
  code_challenge: string;
  code_challenge_method: string;
}

function readAuthorizeParams(source: URLSearchParams): AuthorizeParams {
  return {
    client_id: source.get("client_id") ?? "",
    redirect_uri: source.get("redirect_uri") ?? "",
    state: source.get("state") ?? "",
    code_challenge: source.get("code_challenge") ?? "",
    code_challenge_method: source.get("code_challenge_method") ?? "",
  };
}

function authorizeForm(params: AuthorizeParams, error?: string): Response {
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>La Caja -- Autorizar acceso</title>
<style>body{font-family:system-ui,sans-serif;max-width:420px;margin:80px auto;padding:0 20px;color:#e5e5e5;background:#0b0b0d}
h1{font-size:1.2rem}input{width:100%;padding:10px;margin:12px 0;background:#1a1a1e;border:1px solid #333;color:#fff;border-radius:6px;box-sizing:border-box;font-size:1rem}
button{width:100%;padding:10px;background:#4f7fff;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:1rem}
p{line-height:1.4}.err{color:#ff6b6b}</style></head><body>
<h1>Autorizar acceso a La Caja</h1>
<p>Un cliente MCP pide conectarse en tu nombre. Client ID: <code>${escapeHtml(params.client_id)}</code></p>
${error ? `<p class="err">${escapeHtml(error)}</p>` : ""}
<form method="POST">
<input type="hidden" name="client_id" value="${escapeHtml(params.client_id)}">
<input type="hidden" name="redirect_uri" value="${escapeHtml(params.redirect_uri)}">
<input type="hidden" name="state" value="${escapeHtml(params.state)}">
<input type="hidden" name="code_challenge" value="${escapeHtml(params.code_challenge)}">
<input type="hidden" name="code_challenge_method" value="${escapeHtml(params.code_challenge_method)}">
<input type="password" name="password" placeholder="Password de aprobacion" autofocus required>
<button type="submit">Autorizar</button>
</form>
</body></html>`;
  return new Response(html, { status: 200, headers: { "content-type": "text/html; charset=utf-8" } });
}

function handleAuthorizeGet(url: URL): Response {
  const params = readAuthorizeParams(url.searchParams);
  if (!params.redirect_uri || !params.code_challenge || params.code_challenge_method !== "S256") {
    return new Response("invalid_request: redirect_uri and code_challenge (S256) are required", { status: 400 });
  }
  return authorizeForm(params);
}

async function handleAuthorizePost(request: Request, env: Env): Promise<Response> {
  const form = await request.formData();
  const params: AuthorizeParams = {
    client_id: String(form.get("client_id") ?? ""),
    redirect_uri: String(form.get("redirect_uri") ?? ""),
    state: String(form.get("state") ?? ""),
    code_challenge: String(form.get("code_challenge") ?? ""),
    code_challenge_method: String(form.get("code_challenge_method") ?? ""),
  };
  const password = String(form.get("password") ?? "");
  if (!env.HUMAN_TOKEN || password !== env.HUMAN_TOKEN) {
    return authorizeForm(params, "Password incorrecta.");
  }
  if (!env.OAUTH_SIGNING_KEY) {
    return new Response("server_error: oauth signing key not configured", { status: 500 });
  }
  const code = await signAuthCode(
    { client_id: params.client_id, redirect_uri: params.redirect_uri, code_challenge: params.code_challenge, exp: Date.now() + 5 * 60 * 1000 },
    env.OAUTH_SIGNING_KEY,
  );
  let redirect: URL;
  try {
    redirect = new URL(params.redirect_uri);
  } catch {
    return new Response("invalid_request: malformed redirect_uri", { status: 400 });
  }
  redirect.searchParams.set("code", code);
  if (params.state) redirect.searchParams.set("state", params.state);
  return Response.redirect(redirect.toString(), 302);
}

async function parseTokenParams(request: Request): Promise<URLSearchParams> {
  const contentType = request.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(body)) if (typeof value === "string") params.set(key, value);
    return params;
  }
  return new URLSearchParams(await request.text());
}

async function handleToken(request: Request, env: Env): Promise<Response> {
  const params = await parseTokenParams(request);
  if (params.get("grant_type") !== "authorization_code") return jsonResponse({ error: "unsupported_grant_type" }, 400);
  if (!env.OAUTH_SIGNING_KEY) return jsonResponse({ error: "server_error" }, 500);
  const payload = await verifyAuthCode(params.get("code") ?? "", env.OAUTH_SIGNING_KEY);
  if (!payload) return jsonResponse({ error: "invalid_grant" }, 400);
  if (payload.redirect_uri !== (params.get("redirect_uri") ?? "")) return jsonResponse({ error: "invalid_grant" }, 400);
  const computedChallenge = await sha256base64url(params.get("code_verifier") ?? "");
  if (computedChallenge !== payload.code_challenge) return jsonResponse({ error: "invalid_grant" }, 400);
  if (!env.CHATGPT_TOKEN) return jsonResponse({ error: "server_error" }, 500);
  return jsonResponse({ access_token: env.CHATGPT_TOKEN, token_type: "bearer", expires_in: 315360000, scope: "mcp" });
}

export class CajaState extends DurableObject<Env> {
  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.ctx.storage.sql.exec(`CREATE TABLE IF NOT EXISTS entities (id TEXT PRIMARY KEY, type TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)`);
    this.ctx.storage.sql.exec(`CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, actor TEXT NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL, metadata TEXT NOT NULL, created_at TEXT NOT NULL)`);
  }

  async execute(command: Record<string, unknown>): Promise<Record<string, unknown>> {
    const op = command.op;
    const now = new Date().toISOString();
    if (op === "get_state") return { entities: this.ctx.storage.sql.exec("SELECT * FROM entities ORDER BY updated_at DESC").toArray(), events: this.ctx.storage.sql.exec("SELECT * FROM events ORDER BY created_at ASC").toArray() };
    if (op === "get_entity") {
      const entityId = String(command.entity_id ?? "");
      const entity = this.ctx.storage.sql.exec("SELECT * FROM entities WHERE id = ?", entityId).toArray();
      const history = this.ctx.storage.sql.exec("SELECT * FROM events WHERE entity_id = ? ORDER BY created_at ASC", entityId).toArray();
      if (!entity.length) return { error: "entity_not_found", entity_id: entityId };
      return { entity: entity[0], history };
    }
    if (op === "search_context") {
      const query = `%${String(command.query ?? "")}%`;
      const limit = Math.min(100, Math.max(1, Number(command.limit ?? 20)));
      return { entities: this.ctx.storage.sql.exec("SELECT * FROM entities WHERE title LIKE ? OR type LIKE ? ORDER BY updated_at DESC LIMIT ?", query, query, limit).toArray(), events: this.ctx.storage.sql.exec("SELECT * FROM events WHERE content LIKE ? OR metadata LIKE ? ORDER BY created_at DESC LIMIT ?", query, query, limit).toArray() };
    }
    if (op === "propose") {
      const id = crypto.randomUUID();
      const entityType = String(command.entity_type ?? "proposal");
      const title = String(command.title ?? "");
      const content = String(command.content ?? "");
      const actor = String(command.actor ?? "human");
      this.ctx.storage.sql.exec("INSERT INTO entities (id,type,title,status,created_at,updated_at) VALUES (?,?,?,?,?,?)", id, entityType, title, "candidate", now, now);
      this.ctx.storage.sql.exec("INSERT INTO events (id,entity_id,actor,kind,content,metadata,created_at) VALUES (?,?,?,?,?,?,?)", crypto.randomUUID(), id, actor, "proposal", content, "{}", now);
      return { entity_id: id, status: "candidate" };
    }
    if (op === "challenge") {
      const entityId = String(command.entity_id ?? "");
      const exists = this.ctx.storage.sql.exec("SELECT id FROM entities WHERE id = ?", entityId).toArray();
      if (!exists.length) return { error: "entity_not_found", entity_id: entityId };
      const actor = String(command.actor ?? "human");
      this.ctx.storage.sql.exec("INSERT INTO events (id,entity_id,actor,kind,content,metadata,created_at) VALUES (?,?,?,?,?,?,?)", crypto.randomUUID(), entityId, actor, "challenge", String(command.content ?? ""), JSON.stringify({ targets: command.targets ?? [] }), now);
      return { entity_id: entityId, recorded: true };
    }
    if (op === "update_entity") {
      const entityId = String(command.entity_id ?? "");
      const status = String(command.status ?? "");
      if (!STATUSES.includes(status as Status)) return { error: "invalid_status", status };
      const exists = this.ctx.storage.sql.exec("SELECT id FROM entities WHERE id = ?", entityId).toArray();
      if (!exists.length) return { error: "entity_not_found", entity_id: entityId };
      const actor = String(command.actor ?? "human");
      const content = String(command.content ?? "");
      this.ctx.storage.sql.exec("UPDATE entities SET status = ?, updated_at = ? WHERE id = ?", status, now, entityId);
      this.ctx.storage.sql.exec("INSERT INTO events (id,entity_id,actor,kind,content,metadata,created_at) VALUES (?,?,?,?,?,?,?)", crypto.randomUUID(), entityId, actor, "status_change", content, JSON.stringify({ status }), now);
      return { entity_id: entityId, status };
    }
    if (op === "publish_evidence") {
      const entityId = String(command.entity_id ?? "");
      const exists = this.ctx.storage.sql.exec("SELECT id FROM entities WHERE id = ?", entityId).toArray();
      if (!exists.length) return { error: "entity_not_found", entity_id: entityId };
      const actor = String(command.actor ?? "human");
      this.ctx.storage.sql.exec("INSERT INTO events (id,entity_id,actor,kind,content,metadata,created_at) VALUES (?,?,?,?,?,?,?)", crypto.randomUUID(), entityId, actor, "evidence", String(command.claim ?? ""), JSON.stringify({ source: command.source, notes: command.notes ?? "" }), now);
      return { entity_id: entityId, recorded: true };
    }
    return { error: "unknown_operation", op };
  }
}

function healthResponse(): Response {
  return new Response(JSON.stringify({ status: "ok" }), { status: 200, headers: { "content-type": "application/json" } });
}

export default {
  async fetch(request: Request, env: Env, _ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health") return healthResponse();
    if (url.pathname === "/.well-known/oauth-authorization-server") return jsonResponse(oauthAuthServerMetadata(url.origin));
    if (url.pathname === "/.well-known/oauth-protected-resource") return jsonResponse(oauthProtectedResourceMetadata(url.origin));
    if (url.pathname === "/register" && request.method === "POST") return handleRegister(request);
    if (url.pathname === "/authorize" && request.method === "GET") return handleAuthorizeGet(url);
    if (url.pathname === "/authorize" && request.method === "POST") return handleAuthorizePost(request, env);
    if (url.pathname === "/token" && request.method === "POST") return handleToken(request, env);
    const actor = actorFromToken(request, env);
    if (!actor) return authError(url);
    const handler = createMcpHandler(() => createServer(env, actor));
    return handler.fetch(request);
  },
};
