# SecretarIA Bot — Guia de Instalação

## Estrutura
```
bot_secretaria/
├── bot/                     ← Bot Node.js (WhatsApp)
│   ├── bot.js               ← Entrada principal
│   ├── package.json
│   ├── .env                 ← Crie com PYTHON_API=http://localhost:8080
│   └── src/
│       ├── CommandDispatcher.js
│       ├── models/
│       │   ├── enums.js
│       │   └── StateManager.js
│       ├── services/
│       │   └── IntentParser.js
│       └── commands/
│           ├── AgendaCommand.js
│           ├── GastoCommand.js
│           ├── ConfirmCommand.js
│           └── HelpCommand.js
├── webhook.py               ← API Python (Gemini + SQLite + Google Agenda)
├── .env                     ← Crie com GEMINI_API_KEY=sua_chave
└── secretaria.db            ← Seu banco SQLite existente
```

## Pré-requisitos
- Node.js 18+
- Python 3.10+
- Google Chrome ou Edge instalado (Windows)

## 1. Configurar variáveis de ambiente

### bot_secretaria/.env
```
GEMINI_API_KEY=sua_chave_do_gemini
```

### bot_secretaria/bot/.env
```
PYTHON_API=http://localhost:8080
```

Obtenha a chave Gemini grátis em: https://aistudio.google.com

## 2. Google Agenda & Onboarding Automático (Opção 2)

O bot agora possui um fluxo de onboarding automático e 100% gratuito que funciona em qualquer rede (4G, Wi-Fi escolar, etc.) sem expor seu PC local (sem necessidade de Ngrok).

### Como funciona:
1. O usuário manda qualquer mensagem e o bot inicia o cadastro (Nome, Nascimento, E-mail).
2. O bot gera o link de conexão do Google OAuth e envia no chat.
3. O usuário autoriza no celular e é redirecionado para uma página pública estática (ex: GitHub Pages).
4. Essa página estática lê o código e abre o WhatsApp do usuário com a mensagem pré-preenchida `Confirmar_Conexao: CÓDIGO`.
5. O usuário envia a mensagem, o bot intercepta o código e realiza a ativação localmente de forma segura.

### Como configurar a página estática de redirecionamento:
1. Hospede o arquivo `callback.html` (fornecido na raiz do projeto) em um serviço de hospedagem estática gratuito (ex: **GitHub Pages**, **Vercel** ou **Netlify**).
   * *Exemplo usando GitHub Pages:* Crie um repositório, faça o upload do arquivo `callback.html` e ative o GitHub Pages nas configurações. Seu link será `https://<seu-usuario>.github.io/<repositorio>/callback.html`.
2. Acesse o **[Google Cloud Console](https://console.cloud.google.com/)** -> **APIs e Serviços** -> **Credenciais**.
3. Edite o seu ID de cliente OAuth 2.0 e, em **URIs de redirecionamento autorizados**, adicione a URL exata da sua página hospedada (ex: `https://<seu-usuario>.github.io/<repositorio>/callback.html`).
4. Edite o arquivo `.env` na raiz do projeto e configure a variável `OAUTH_REDIRECT_URI` com essa mesma URL:
   ```env
   OAUTH_REDIRECT_URI=https://<seu-usuario>.github.io/<repositorio>/callback.html
   ```

## 3. Banco de dados
O webhook.py usa o mesmo secretaria.db do seu projeto.
Certifique que a tabela `usuarios` tem a coluna `telefone`
com o número no formato só dígitos: 556299999999

## 4. Rodar o bot

### Terminal 1 — Backend Python
```bash
cd bot_secretaria
python webhook.py
```
(instala dependências automaticamente na 1ª vez)

### Terminal 2 — Bot WhatsApp
```bash
cd bot_secretaria/bot
node bot.js
```
(instala dependências automaticamente na 1ª vez)

Escaneie o QR Code que aparecer no terminal com seu WhatsApp.
A sessão fica salva em .wwebjs_auth/ — não precisa escanear toda vez.

## 5. Fluxo de funcionamento

```
TEXTO  → IntentParser local (ZERO chamadas ao Gemini)
ÁUDIO  → Gemini transcreve + extrai intenção → executa
IMAGEM → Gemini analisa recibo → pede confirmação → registra gasto
```

## Comandos de texto reconhecidos
- "ver agenda hoje" / "agenda da semana"
- "quando estou livre amanhã"
- "agendar reunião sexta às 15h"
- "cancelar reunião das 15h"
- "gastei 45 reais no almoço"
- "ver meus gastos do mês"
- "definir teto de 3000 reais"
- "ajuda"
