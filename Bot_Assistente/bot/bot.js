// ─────────────────────────────────────────────────────────────────────
//  SecretarIA — bot.js
//  Auto-instala dependências, detecta Chrome e inicializa o bot
// ─────────────────────────────────────────────────────────────────────
const { execSync, spawn } = require('child_process');
const fs   = require('fs');
const path = require('path');

const DEPS = ['whatsapp-web.js','qrcode-terminal','axios','form-data','dotenv'];

function instalado(dep) { try { require.resolve(dep); return true; } catch { return false; } }

const faltando = DEPS.filter(d => !instalado(d));
if (faltando.length > 0) {
  console.log('📦 Instalando dependências: ' + faltando.join(', '));
  console.log('⏳ Pode demorar alguns minutos na 1ª vez...\n');
  try {
    execSync(`npm install ${faltando.join(' ')}`, { stdio: 'inherit', cwd: __dirname });
    console.log('\n✅ Instalado! Reiniciando...\n');
    const child = spawn(process.execPath, process.argv.slice(1), { stdio: 'inherit', cwd: process.cwd() });
    child.on('exit', code => process.exit(code));
    return;
  } catch (err) { console.error('❌ Erro ao instalar:', err.message); process.exit(1); }
}

require('dotenv').config();
const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode               = require('qrcode-terminal');
const CommandDispatcher    = require('./src/CommandDispatcher');

function detectarChrome() {
  const local = process.env.LOCALAPPDATA || '';
  const candidatos = [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    local + '\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    local + '\\Microsoft\\Edge\\Application\\msedge.exe',
  ];
  for (const p of candidatos) {
    if (p && fs.existsSync(p)) { console.log(`🌐 Browser: ${path.basename(p)}`); return p; }
  }
  return undefined;
}

const client = new Client({
  authStrategy: new LocalAuth({ dataPath: path.join(__dirname, '.wwebjs_auth') }),
  puppeteer: {
    headless: true,
    executablePath: detectarChrome(),
    args: ['--no-sandbox','--disable-setuid-sandbox','--disable-dev-shm-usage',
           '--disable-gpu','--disable-extensions','--no-first-run','--mute-audio'],
    timeout: 60000,
  },
});

const bot        = { sendMessage: (to, text) => client.sendMessage(to, text) };
const dispatcher = new CommandDispatcher(bot);
let   reconexoes = 0;

client.on('qr', qr => {
  console.clear();
  console.log('╔══════════════════════════════════════════╗');
  console.log('║    [o_o]  S E C R E T A R I A  Bot      ║');
  console.log('╠══════════════════════════════════════════╣');
  console.log('║  WhatsApp → Dispositivos conectados      ║');
  console.log('║            → Conectar dispositivo        ║');
  console.log('╚══════════════════════════════════════════╝\n');
  qrcode.generate(qr, { small: true });
  console.log('\n⏳ Aguardando escaneamento...\n');
});

client.on('authenticated', () => { reconexoes = 0; console.log('🔐 Autenticado! Sessão salva.'); });

client.on('ready', () => {
  console.log('\n✅ SecretarIA online!');
  console.log('🎙️  Áudio  → Gemini transcreve e executa ação');
  console.log('🖼️  Imagem → Gemini lê recibo e registra gasto');
  console.log('💬  Texto  → Processado localmente (zero tokens)\n');
});

client.on('auth_failure', () => {
  console.error('❌ Falha na autenticação. Delete a pasta .wwebjs_auth/ e tente novamente.');
  process.exit(1);
});

client.on('disconnected', reason => {
  console.warn(`\n⚠️  Desconectado: ${reason}`);
  if (reconexoes < 5) {
    reconexoes++;
    const delay = reconexoes * 5000;
    console.log(`🔄 Reconexão ${reconexoes}/5 em ${delay/1000}s...`);
    setTimeout(() => client.initialize().catch(console.error), delay);
  } else { console.error('❌ Máx. reconexões. Reinicie manualmente.'); process.exit(1); }
});

client.on('message_create', async msg => {
  // Evita processar mensagens enviadas pelo próprio bot
  if (msg.fromMe || msg.id?.fromMe) return;

  // Como garantia extra, verifica se o remetente é o próprio bot
  const botNumber = client.info?.wid?.user;
  if (botNumber && msg.from?.startsWith(botNumber)) return;

  await dispatcher.dispatch(msg);
});

const http = require('http');

const server = http.createServer((req, res) => {
  let body = '';
  req.on('data', chunk => { body += chunk; });
  req.on('end', async () => {
    try {
      if (req.method === 'POST' && req.url === '/send') {
        const data = JSON.parse(body);
        if (data.to && data.text) {
          const formattedTo = data.to.includes('@c.us') ? data.to : `${data.to}@c.us`;
          await client.sendMessage(formattedTo, data.text);
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ success: true }));
        } else {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Missing to or text' }));
        }
      } else if (req.method === 'POST' && req.url === '/oauth/success') {
        const data = JSON.parse(body);
        if (data.phone && data.text) {
          const StateManager = require('./src/models/StateManager');
          StateManager.clearState(data.phone);
          const formattedTo = data.phone.includes('@c.us') ? data.phone : `${data.phone}@c.us`;
          await client.sendMessage(formattedTo, data.text);
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ success: true }));
        } else {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Missing phone or text' }));
        }
      } else {
        res.writeHead(404);
        res.end();
      }
    } catch (err) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: err.message }));
    }
  });
});

server.listen(5001, () => {
  console.log('📢 Bot HTTP listener online na porta 5001 (para envio de lembretes/briefings)');
});

process.on('SIGINT', async () => {
  console.log('\n🛑 Encerrando...'); await client.destroy(); process.exit(0);
});

console.log('\n🚀 Iniciando SecretarIA Bot...\n');
client.initialize().catch(err => { console.error('❌ Erro:', err.message); process.exit(1); });
