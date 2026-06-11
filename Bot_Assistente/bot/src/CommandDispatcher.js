require('dotenv').config();
const { classificar }  = require('./services/IntentParser');
const StateManager     = require('./models/StateManager');
const { Intent }       = require('./models/enums');
const HelpCommand      = require('./commands/HelpCommand');
const AgendaCommand    = require('./commands/AgendaCommand');
const GastoCommand     = require('./commands/GastoCommand');
const ConfirmCommand   = require('./commands/ConfirmCommand');

const processedMessages = new Set();

class CommandDispatcher {
  constructor(bot) {
    this.bot        = bot;
    this.confirmCmd = new ConfirmCommand();
    this.commands   = [new AgendaCommand(), new GastoCommand(), new HelpCommand()];
  }

  async dispatch(msg) {
    if (msg.from.endsWith('@g.us') || msg.from === 'status@broadcast') return;

    // Evita processar mensagens duplicadas (muito comum no whatsapp-web.js)
    if (msg.id && msg.id._serialized) {
      if (processedMessages.has(msg.id._serialized)) {
        console.log(`[Dispatcher] Ignorando mensagem duplicada: ${msg.id._serialized}`);
        return;
      }
      processedMessages.add(msg.id._serialized);
      if (processedMessages.size > 1000) {
        const first = processedMessages.values().next().value;
        processedMessages.delete(first);
      }
    }

    const phone = msg.from.replace('@c.us', '');
    const ctx   = StateManager.getState(phone);
    const tipo  = msg.type;
    const hora  = new Date().toLocaleTimeString('pt-BR');
    const axios = require('axios');
    const API   = process.env.PYTHON_API || 'http://localhost:8080';

    console.log(`[${hora}] ${phone} | tipo:${tipo} | state:${ctx.state}`);

    try {
      // Se for mensagem de confirmação de conexão do Google OAuth (Opção 2)
      const textoMensagem = msg.body?.trim();
      if (textoMensagem && textoMensagem.startsWith('Confirmar_Conexao:')) {
        console.log(`[Dispatcher] Mensagem de confirmação de conexão recebida para ${phone}`);
        const code = textoMensagem.replace('Confirmar_Conexao:', '').trim();
        try {
          const resVerify = await axios.post(`${API}/onboarding/verificar`, { phone });
          const userStatus = resVerify.data;
          if (userStatus.cadastrado) {
            await this.bot.sendMessage(msg.from, '⏳ Verificando e conectando sua conta...');
            await axios.post(`${API}/onboarding/confirmar_code`, {
              phone,
              code,
              userId: userStatus.id
            });
            StateManager.clearState(phone);
            await this.bot.sendMessage(msg.from,
              `🚀 *Tudo pronto! Bem-vindo(a) à SecretarIA!* 🎉\n\n` +
              `Agora posso gerenciar seus *compromissos* e *finanças*!\n\n` +
              `📚 *Exemplos do que posso fazer:*\n` +
              `• _"Reunião com Ana sexta às 15h"_\n` +
              `• _"Coloca dentista amanhã às 10h"_\n` +
              `• _"Ver agenda de hoje"_\n` +
              `• _"Gastei 45 reais no almoço"_\n` +
              `• _"Ver meus gastos do mês"_\n\n` +
              `💡 Digite *ajuda* para ver todos os comandos! 😊`
            );
            return;
          }
        } catch (errConfirm) {
          console.error('[Dispatcher/Confirmar_Conexao]', errConfirm.message);
          await this.bot.sendMessage(msg.from, '⚠️ Falha ao conectar conta do Google Agenda. Verifique se o código expirou ou tente novamente.');
          return;
        }
      }

      // ── Verificar se o usuário está cadastrado e conectado ─────────────────
      if (ctx.state === 'IDLE') {
        try {
          const res = await axios.post(`${API}/onboarding/verificar`, { phone });
          const userStatus = res.data;
          if (!userStatus.cadastrado) {
            // Salva o ID da mensagem que disparou o onboarding para não processá-la como nome
            StateManager.setState(phone, 'ONBOARDING_NOME', { triggerMsgId: msg.id?._serialized });
            await this.bot.sendMessage(msg.from, 
              `👋 Olá! Sou a *SecretarIA*, sua assistente pessoal de agenda e finanças no WhatsApp.\n\n` +
              `Notei que você ainda não tem cadastro no sistema. Vamos começar?\n\n` +
              `👉 Por favor, digite seu *nome completo*:`);
            return;
          } else if (!userStatus.google_conectado) {
            StateManager.setState(phone, 'ONBOARDING_OAUTH', { userId: userStatus.id });
            try {
              const botPhone = msg.to.replace('@c.us', '');
              const authRes = await axios.post(`${API}/onboarding/auth_url`, { phone, botPhone });
              await this.bot.sendMessage(msg.from,
                `👋 Olá, *${userStatus.nome.split(' ')[0]}*!\n\n` +
                `Seu cadastro existe, mas precisamos conectar sua conta do Google Agenda.\n\n` +
                `📌 Acesse o link abaixo para autorizar:\n${authRes.data.url}\n\n` +
                `_Após autorizar, a página solicitará para abrir o WhatsApp e enviar a mensagem de confirmação pré-preenchida. Basta clicar em Enviar!_`);
              return;
            } catch (authErr) {
              console.error('[Dispatcher/auth_url]', authErr.message);
              StateManager.clearState(phone);
              const errorMsg = authErr.response?.data?.erro || 'Erro ao gerar link de conexão com o Google Agenda.';
              await this.bot.sendMessage(msg.from, `⚠️ ${errorMsg}\nPor favor, tente novamente mais tarde.`);
              return;
            }
          }
        } catch (err) {
          console.error('[Dispatcher/verificar]', err.message);
          StateManager.clearState(phone);
          if (err.code === 'ECONNREFUSED') {
            await this.bot.sendMessage(msg.from, '⚠️ Servidor backend offline. Por favor, inicie o webhook.py e tente novamente.');
          } else {
            await this.bot.sendMessage(msg.from, '⚠️ Não foi possível verificar seu cadastro. Tente novamente mais tarde.');
          }
          return;
        }
      }

      // ── Se está no fluxo de onboarding, delega ─────────────────────
      if (ctx.state.startsWith('ONBOARDING_')) {
        const OnboardingCommand = require('./commands/OnboardingCommand');
        const onboardingCmd = new OnboardingCommand();
        await onboardingCmd.execute(msg, ctx, this.bot);
        return;
      }

      // ── Áudio ou Imagem: delega ao webhook Python (Gemini) ────────────
      if (tipo === 'ptt' || tipo === 'audio' || tipo === 'image') {
        await this._processarMidia(msg, tipo, phone);
        return;
      }

      // ── Texto: processa localmente ou via IA ──────────────────────
      const texto = msg.body?.trim();
      if (!texto) return;

      console.log(`[${hora}] Texto: "${texto.substring(0, 60)}"`);

      // Aguardando confirmar exclusão de conta?
      if (ctx.state === 'EXCLUIR_CONTA_CONFIRMANDO') {
        const { intent } = classificar(texto);
        await this.confirmCmd.execute(msg, ctx, this.bot, intent);
        return;
      }

      // Usuário quer excluir a conta? (detecta antes de qualquer outra coisa)
      const textoLower = texto.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
      const pedidoExclusao = /\b(excluir|deletar|remover|apagar|cancelar).*(conta|cadastro|perfil)\b|\b(quero|vou|vamos)\s+(sair|cancelar|me\s+excluir|me\s+remover)\b/.test(textoLower);
      if (pedidoExclusao && ctx.state === 'IDLE') {
        StateManager.setState(phone, 'EXCLUIR_CONTA_CONFIRMANDO', {});
        await this.bot.sendMessage(msg.from,
          `⚠️ *Você tem certeza que deseja excluir sua conta?*\n\n` +
          `Isso irá remover permanentemente:\n` +
          `• Seu cadastro e dados pessoais\n` +
          `• Todos os seus gastos registrados\n` +
          `• Suas categorias e tetos financeiros\n` +
          `• A conexão com o Google Agenda\n\n` +
          `🔴 *Esta ação não pode ser desfeita!*\n\n` +
          `Responda *sim* para confirmar ou *não* para cancelar.`
        );
        return;
      }

      // 1. Estado ativo?
      if (ctx.state !== 'IDLE') {
        const { intent } = classificar(texto);
        const isNumero = !isNaN(parseFloat(texto.replace(',', '.').replace(/[^\d.]/g, '')));
        
        // Se for um comando conhecido E não for apenas um número, cancela o estado anterior e executa o novo comando
        if (intent !== Intent.DESCONHECIDO && intent !== Intent.CONFIRMAR && intent !== Intent.NEGAR && !isNumero) {
          console.log(`[Dispatcher] Novo comando detectado durante estado ativo (${ctx.state}). Cancelando estado e executando.`);
          StateManager.clearState(phone);
          // O fluxo continua abaixo para executar o novo comando
        } else {
          // Deixa o ConfirmCommand tratar (sim/não ou digitação de valores)
          if (this.confirmCmd.canHandle(null, ctx)) {
            await this.confirmCmd.execute(msg, ctx, this.bot, intent);
            return;
          }
        }
      }

      // 2. Classifica localmente
      const { intent, dados } = classificar(texto);
      console.log(`[${hora}] Intent local: ${intent}`);

      // 3. Despacha para o comando correto se conhecido localmente
      if (intent !== Intent.DESCONHECIDO) {
        const command = this.commands.find(cmd => cmd.canHandle(intent, ctx));
        if (command) {
          await command.execute(msg, ctx, this.bot, intent, dados);
          return;
        }
      }

      // 4. Fallback de IA para texto livre (Gemini no Flask)
      await this._processarTextoViaIA(msg, texto, phone);

    } catch (err) {
      console.error(`[Dispatcher] Erro ${phone}:`, err.message);
      try { await this.bot.sendMessage(msg.from, '😕 Algo deu errado. Tente novamente.'); } catch (_) {}
    }
  }

  async _processarTextoViaIA(msg, texto, phone) {
    const axios = require('axios');
    const API   = process.env.PYTHON_API || 'http://localhost:8080';
    try {
      await this.bot.sendMessage(msg.from, '⏳ Processando...');
      const res = await axios.post(`${API}/texto`, { phone, texto });
      await this.bot.sendMessage(msg.from, res.data.texto);
      
      if (res.data.pendente && res.data.estado) {
        StateManager.setState(phone, res.data.estado, res.data.dados || {});
      }
    } catch (err) {
      console.error('[Dispatcher/texto]', err.message);
      await this.bot.sendMessage(msg.from, err.code === 'ECONNREFUSED'
        ? '⚠️ Servidor Python offline. Inicie o webhook.py.'
        : '⚠️ Não consegui processar a mensagem. Tente novamente.');
    }
  }

  async _processarMidia(msg, tipo, phone) {
    const axios    = require('axios');
    const FormData = require('form-data');
    const fs       = require('fs');
    const path     = require('path');

    const API      = process.env.PYTHON_API || 'http://localhost:8080';
    const TEMP_DIR = path.join(__dirname, '../temp');
    if (!fs.existsSync(TEMP_DIR)) fs.mkdirSync(TEMP_DIR, { recursive: true });

    const isAudio = tipo === 'ptt' || tipo === 'audio';
    const ext     = isAudio ? 'ogg' : 'jpg';
    const temp    = path.join(TEMP_DIR, `${Date.now()}.${ext}`);

    await msg.reply('⏳ Processando...');

    try {
      const media = await msg.downloadMedia();
      if (!media?.data) { await msg.reply('⚠️ Não consegui baixar. Tente novamente.'); return; }

      fs.writeFileSync(temp, Buffer.from(media.data, 'base64'));

      const form = new FormData();
      form.append('file',  fs.createReadStream(temp));
      form.append('type',  isAudio ? 'audio' : 'image');
      form.append('phone', phone);

      const endpoint = isAudio ? '/media/audio' : '/media/imagem';
      const res = await axios.post(`${API}${endpoint}`, form, { headers: form.getHeaders(), timeout: 120000 });
      const resposta = res.data?.texto || '✅ Processado.';
      await msg.reply(resposta);

      if (res.data?.pendente && res.data?.estado) {
        StateManager.setState(phone, res.data.estado, res.data.dados || {});
      }
    } catch (err) {
      console.error('[Dispatcher/midia] Erro:', err.message);
      if (err.response) {
        console.error('[Dispatcher/midia] Status HTTP:', err.response.status);
        console.error('[Dispatcher/midia] Resposta API:', JSON.stringify(err.response.data));
      }
      await msg.reply(err.code === 'ECONNREFUSED'
        ? '⚠️ Servidor Python offline. Inicie o webhook.py e tente novamente.'
        : '⚠️ Não consegui processar. Tente novamente.');
    } finally {
      if (fs.existsSync(temp)) fs.unlinkSync(temp);
    }
  }
}

module.exports = CommandDispatcher;
