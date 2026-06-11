# 🤖 SecretarIA — Bot Assistente WhatsApp

```
 [o_o]
 /|_|\
S E C R E T A R I A — Bot WhatsApp
```

Assistente pessoal inteligente via WhatsApp, com integração ao Google Calendar, controle financeiro e respostas por IA (Gemini).

---

## ✨ Funcionalidades

- 📅 **Agenda** — consulta e criação de eventos no Google Calendar
- 💸 **Controle de gastos** — registro de despesas por mensagem
- 🎤 **Transcrição de áudio** — envia um áudio e o bot transcreve e responde
- 🤖 **IA conversacional** — respostas inteligentes via Gemini 2.5 Flash
- 📋 **Onboarding guiado** — configuração inicial direto pelo WhatsApp

---

## 🗂️ Estrutura do projeto

```
Bot_Assistente/
├── bot/                        # Bot Node.js (whatsapp-web.js)
│   └── src/
│       ├── commands/           # Comandos: agenda, gastos, ajuda...
│       ├── models/             # Gerenciamento de estado
│       └── services/           # Parser de intenções (IA)
├── webhook.py                  # Servidor Flask (webhook)
├── secretaria_cli.py           # Interface de linha de comando
├── callback.html               # Página de callback OAuth Google
├── .env                        # Variáveis de ambiente (não versionado)
├── credentials.json            # Credenciais Google (não versionado)
└── .gitignore
```

---

## 🚀 Como instalar e rodar

### Pré-requisitos

- Node.js 18+
- Python 3.10+
- Conta Google com Google Calendar ativado
- Chave de API da [Gemini](https://aistudio.google.com/)

### 1. Clone o repositório

```bash
git clone https://github.com/allan-victor594/SecretarIA.git
cd SecretarIA/Bot_Assistente
```

### 2. Configure as variáveis de ambiente

Crie um arquivo `.env` na raiz do projeto:

```env
GEMINI_API_KEY=sua_chave_aqui
WEBHOOK_URL=https://seu-dominio.ngrok.io
```

### 3. Instale as dependências do bot (Node.js)

```bash
cd bot
npm install
```

### 4. Instale as dependências do servidor (Python)

```bash
pip install flask google-auth google-auth-oauthlib google-api-python-client
```

### 5. Rode o servidor webhook

```bash
python webhook.py
```

### 6. Rode o bot

```bash
cd bot
node bot.js
```

Escaneie o QR Code que aparecer no terminal com o WhatsApp.

---

## 💰 Custos estimados (Gemini)

O modelo `gemini-2.5-flash-lite` tem cota gratuita generosa:

- ~1.500 requisições/dia no plano gratuito
- Áudio e imagem consomem menos que texto longo
- Para uso com 10–15 pessoas = bem dentro do limite gratuito

---

## 🛠️ Tecnologias

| Tecnologia | Uso |
|---|---|
| [whatsapp-web.js](https://github.com/pedroslopez/whatsapp-web.js) | Conexão com WhatsApp |
| [Google Gemini API](https://aistudio.google.com/) | Inteligência artificial |
| [Google Calendar API](https://developers.google.com/calendar) | Gestão de agenda |
| [Flask](https://flask.palletsprojects.com/) | Servidor webhook (Python) |
| [SQLite](https://www.sqlite.org/) | Banco de dados local |
| [ngrok](https://ngrok.com/) | Túnel para desenvolvimento local |

---

## ⚠️ Segurança

Os seguintes arquivos **nunca** devem ser commitados:

- `.env` — chaves de API
- `credentials.json` — credenciais OAuth do Google
- `tokens/` — tokens de acesso
- `*.db` — banco de dados local

Todos já estão protegidos pelo `.gitignore`.

---

## 👨‍💻 Autor

**Allan Victor** — [@allan-victor594](https://github.com/allan-victor594)  
Estudante de Engenharia de Software — UniGoiás  
Estágio: Unimed Goiânia