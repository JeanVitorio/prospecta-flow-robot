"use strict";

const http = require("http");
const path = require("path");
const QRCode = require("qrcode");
const { Client, LocalAuth } = require("whatsapp-web.js");

const host = "127.0.0.1";
const port = Number(process.env.WHATSAPP_GATEWAY_PORT || 32145);
const token = process.env.WHATSAPP_GATEWAY_TOKEN || "";
const dataPath =
  process.env.WHATSAPP_SESSION_PATH ||
  path.join(__dirname, "..", "dados_whatsapp");
const chromePath = (process.env.CHROME_BIN || "").trim();
const sessions = new Map();

if (!token) {
  throw new Error("WHATSAPP_GATEWAY_TOKEN é obrigatório.");
}

function validSessionId(value) {
  return /^[0-9a-f-]{36}$/i.test(String(value || ""));
}

function normalizePhone(value) {
  let digits = String(value || "").replace(/\D/g, "");
  if (digits.length === 10 || digits.length === 11) digits = `55${digits}`;
  if (digits.length < 12 || digits.length > 15) return "";
  return digits;
}

function publicState(state) {
  return {
    status: state.status,
    qr_code_data_url: state.qrCodeDataUrl,
    qr_generated_at: state.qrGeneratedAt,
    connected_number: state.connectedNumber,
    last_error: state.lastError,
  };
}

function createSession(sessionId) {
  const state = {
    status: "connecting",
    qrCodeDataUrl: null,
    qrGeneratedAt: null,
    connectedNumber: null,
    lastError: null,
    queue: Promise.resolve(),
    client: null,
  };
  const puppeteer = {
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  };
  if (chromePath) puppeteer.executablePath = chromePath;

  const client = new Client({
    authStrategy: new LocalAuth({ clientId: sessionId, dataPath }),
    puppeteer,
  });
  state.client = client;

  client.on("qr", async (qr) => {
    state.status = "qr_pending";
    state.qrCodeDataUrl = await QRCode.toDataURL(qr, {
      errorCorrectionLevel: "M",
      margin: 2,
      width: 320,
    });
    state.qrGeneratedAt = new Date().toISOString();
    state.lastError = null;
  });
  client.on("authenticated", () => {
    state.status = "connecting";
    state.qrCodeDataUrl = null;
  });
  client.on("ready", () => {
    state.status = "ready";
    state.connectedNumber = client.info?.wid?.user || null;
    state.qrCodeDataUrl = null;
    state.qrGeneratedAt = null;
    state.lastError = null;
  });
  client.on("auth_failure", (message) => {
    state.status = "error";
    state.lastError = String(message || "Falha de autenticação").slice(0, 500);
  });
  client.on("disconnected", (reason) => {
    state.status = "disconnected";
    state.connectedNumber = null;
    state.lastError = String(reason || "Sessão desconectada").slice(0, 500);
  });

  client.initialize().catch((error) => {
    state.status = "error";
    state.lastError = String(error?.message || error).slice(0, 500);
  });
  sessions.set(sessionId, state);
  return state;
}

function getOrCreateSession(sessionId) {
  if (!validSessionId(sessionId)) throw new Error("Sessão inválida.");
  const existing = sessions.get(sessionId);
  if (
    existing &&
    !["disconnected", "error"].includes(existing.status)
  ) {
    return existing;
  }
  if (existing) {
    existing.client.destroy().catch(() => undefined);
    sessions.delete(sessionId);
  }
  return createSession(sessionId);
}

function enqueue(state, task) {
  const result = state.queue.then(task, task);
  state.queue = result.catch(() => undefined);
  return result;
}

async function readJson(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 32 * 1024) throw new Error("Requisição muito grande.");
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function respond(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
    "cache-control": "no-store",
  });
  response.end(body);
}

async function route(request, response) {
  if (request.headers.authorization !== `Bearer ${token}`) {
    respond(response, 401, { error: "Não autorizado." });
    return;
  }
  if (request.method === "GET" && request.url === "/health") {
    respond(response, 200, { status: "ok" });
    return;
  }
  if (request.method !== "POST") {
    respond(response, 404, { error: "Rota não encontrada." });
    return;
  }

  const body = await readJson(request);
  const sessionId = String(body.session_id || "");
  if (!validSessionId(sessionId)) {
    respond(response, 400, { error: "Sessão inválida." });
    return;
  }

  if (request.url === "/sessions/connect") {
    const state = getOrCreateSession(sessionId);
    respond(response, 200, publicState(state));
    return;
  }

  const state = sessions.get(sessionId);
  if (!state) {
    respond(response, 409, { error: "Sessão ainda não foi iniciada." });
    return;
  }
  if (request.url === "/sessions/status") {
    respond(response, 200, publicState(state));
    return;
  }
  if (state.status !== "ready") {
    respond(response, 409, { error: "WhatsApp ainda não está conectado." });
    return;
  }

  const phone = normalizePhone(body.phone);
  if (!phone) {
    respond(response, 200, { exists: false, reason: "invalid_format" });
    return;
  }

  if (request.url === "/numbers/validate") {
    const numberId = await enqueue(state, () => state.client.getNumberId(phone));
    respond(response, 200, {
      exists: Boolean(numberId),
      whatsapp_id: numberId?._serialized || null,
    });
    return;
  }
  if (request.url === "/messages/send") {
    const message = String(body.message || "").trim();
    if (!message || message.length > 4000) {
      respond(response, 400, { error: "Mensagem inválida." });
      return;
    }
    const numberId = await enqueue(state, () => state.client.getNumberId(phone));
    if (!numberId) {
      respond(response, 200, { sent: false, exists: false });
      return;
    }
    const sent = await enqueue(state, () =>
      state.client.sendMessage(numberId._serialized, message),
    );
    respond(response, 200, {
      sent: true,
      exists: true,
      message_id: sent?.id?._serialized || null,
    });
    return;
  }
  respond(response, 404, { error: "Rota não encontrada." });
}

const server = http.createServer((request, response) => {
  route(request, response).catch((error) => {
    respond(response, 500, {
      error: String(error?.message || error).slice(0, 500),
    });
  });
});

server.listen(port, host, () => {
  console.log(`Gateway WhatsApp ativo em http://${host}:${port}`);
});

async function shutdown() {
  server.close();
  await Promise.allSettled(
    [...sessions.values()].map((state) => state.client.destroy()),
  );
  process.exit(0);
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
