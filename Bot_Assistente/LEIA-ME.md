```
 [o_o]
 /|_|\
S E C R E T A R I A  —  Bot WhatsApp
```

## Estrutura do projeto

```
secretaria_final/
├── bot/
│   ├── bot.js              ← Bot Node.js (WhatsApp Web + QR)
│   └── package.json
│
├── secretaria_cli.py        ← Seu sistema original (menu CLI)
├── webhook.py               ← Novo: API que processa áudio e imagem
├── .env                     ← Suas chaves (já existe)
├── credentials.json         ← Google OAuth (já existe)
└── tokens/                  ← Tokens de usuários (já existe)
```

---

## Como funciona

```
WhatsApp (celular)
      │  áudio ou foto
      ▼
 bot.js (Node.js)          ← exibe QR, recebe mensagens
      │  POST /webhook/media
      ▼
 webhook.py (Python)       ← processa com Gemini
      │  resposta pronta
      ▼
 bot.js envia reply        ← texto de volta ao WhatsApp
```

Mensagens de **texto são 100% ignoradas** — só áudio e imagem chegam à IA.

---

## Passo a Passo

### Pré-requisitos
- Python 3.10+ instalado
- Node.js 18+ instalado → https://nodejs.org
- Arquivo `.env` com `GEMINI_API_KEY=...` (já existe no projeto)

---

### 1. Instalar dependências Node.js (apenas 1ª vez)

```bash
cd secretaria_final/bot
npm install
```
> Aguarde — baixa o Chromium junto (~300MB na 1ª vez).

---

### 2. Instalar dependências Python (apenas 1ª vez)

```bash
cd secretaria_final
pip install flask google-genai python-dotenv
```

---

### 3. Rodar o Webhook Python — Terminal 1

```bash
cd secretaria_final
python webhook.py
```

Você verá:
```
[09:00:00] INFO - ✅ Gemini configurado | Modelo: gemini-2.5-flash-lite
[09:00:00] INFO - 🚀 SecretarIA Webhook iniciado na porta 5000
```

---

### 4. Rodar o Bot Node.js — Terminal 2

```bash
cd secretaria_final/bot
node bot.js
```

Um QR Code aparece no terminal:
```
╔══════════════════════════════════════════╗
║    [o_o]  S E C R E T A R I A  Bot      ║
╚══════════════════════════════════════════╝

█████████████████
█ ▄▄▄▄▄ ██ ▄ ▄ █
...
```

---

### 5. Conectar o WhatsApp

1. Abra o WhatsApp no celular
2. Vá em: **Configurações → Dispositivos conectados → Conectar dispositivo**
3. Escaneie o QR Code que aparece no Terminal 2
4. Aguarde: `✅ SecretarIA Bot conectado e pronto!`

> 💡 A sessão fica salva em `bot/.wwebjs_auth/`.
> Na próxima vez, só rode `node bot.js` — não precisa escanear de novo.

---

### 6. Testar

- Grave um **áudio** no WhatsApp e mande para o número conectado
- Mande uma **foto** (recibo, documento, qualquer imagem)
- O bot responde automaticamente com transcrição ou análise

---

## Rodar o menu CLI normal (sem bot)

O `secretaria_cli.py` continua funcionando normalmente:

```bash
cd secretaria_final
python secretaria_cli.py
```

Os dois podem rodar ao mesmo tempo sem conflito.

---

## Problemas comuns

| Problema | Solução |
|---|---|
| `ECONNREFUSED` no bot.js | Webhook Python não está rodando — inicie o Terminal 1 |
| QR não aparece | Rode `npm install` dentro da pasta `bot/` |
| Bot desconecta | Delete `bot/.wwebjs_auth/` e escaneie o QR novamente |
| `GEMINI_API_KEY não encontrada` | Verifique se o arquivo `.env` está na pasta `secretaria_final/` |
| Áudio não transcreve | Arquivo pode estar corrompido — tente com outro áudio |

---

## Custos estimados (Gemini)

O modelo `gemini-2.5-flash-lite` tem **cota gratuita generosa**:
- ~1.500 requisições/dia no plano gratuito
- Áudio e imagem consomem menos que texto longo
- Para uso com 10-15 pessoas = bem dentro do limite gratuito
