const StateManager = require('../models/StateManager');
const axios = require('axios');
const API = process.env.PYTHON_API || 'http://localhost:8080';

class OnboardingCommand {
  async execute(msg, ctx, bot) {
    const phone = msg.from.replace('@c.us', '');
    const text = msg.body.trim();

    switch (ctx.state) {
      case 'ONBOARDING_NOME': {
        // Ignora a primeira mensagem que disparou o onboarding (ex: "Oi", "Bom dia")
        const msgId = msg.id?._serialized;
        if (msgId && ctx.data.triggerMsgId && msgId === ctx.data.triggerMsgId) {
          console.log(`[Onboarding] Ignorando mensagem gatilho: ${msgId}`);
          return;
        }
        if (text.length < 3) {
          await bot.sendMessage(msg.from, '⚠️ O nome deve ter pelo menos 3 caracteres. Digite novamente:');
          return;
        }
        StateManager.setState(phone, 'ONBOARDING_DATA_NASC', { nome: text });
        await bot.sendMessage(msg.from,
          `Prazer, *${text.split(' ')[0]}*! 😊\n\n` +
          `📅 Agora digite sua *data de nascimento* no formato:\n*DD/MM/AAAA*\n\n` +
          `_Exemplo: 15/03/1990_`
        );
        break;
      }

      case 'ONBOARDING_DATA_NASC': {
        const regexData = /^\d{2}\/\d{2}\/\d{4}$/;
        if (!regexData.test(text)) {
          await bot.sendMessage(msg.from, '⚠️ Formato inválido. Digite no formato *DD/MM/AAAA*:\n_Exemplo: 15/03/1990_');
          return;
        }
        // Valida se a data é real
        const [dia, mes, ano] = text.split('/').map(Number);
        const dataTest = new Date(ano, mes - 1, dia);
        if (dataTest.getDate() !== dia || dataTest.getMonth() !== mes - 1 || dataTest.getFullYear() !== ano) {
          await bot.sendMessage(msg.from, '⚠️ Data inválida. Verifique o dia, mês e ano e tente novamente:');
          return;
        }
        StateManager.setState(phone, 'ONBOARDING_EMAIL', { ...ctx.data, data_nasc: text });
        await bot.sendMessage(msg.from, `✅ Data recebida!\n\n📧 Agora, qual é o seu *e-mail*?`);
        break;
      }

      case 'ONBOARDING_EMAIL': {
        const regexEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!regexEmail.test(text)) {
          await bot.sendMessage(msg.from, '⚠️ E-mail inválido. Por favor, digite um e-mail válido:');
          return;
        }

        // Salva os dados e pede confirmação antes de criar a conta
        StateManager.setState(phone, 'ONBOARDING_CONFIRMAR', {
          nome: ctx.data.nome,
          data_nasc: ctx.data.data_nasc,
          email: text
        });

        await bot.sendMessage(msg.from,
          `📋 *Confirme seus dados antes de continuar:*\n\n` +
          `👤 *Nome:* ${ctx.data.nome}\n` +
          `📅 *Data de nasc.:* ${ctx.data.data_nasc}\n` +
          `📧 *E-mail:* ${text}\n\n` +
          `Os dados estão corretos?\n` +
          `✅ *sim* — criar minha conta\n` +
          `❌ *não* — corrigir os dados`
        );
        break;
      }

      case 'ONBOARDING_CONFIRMAR': {
        const resposta = text.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');

        const confirmou = /^(sim|s|ok|pode|confirma|certo|claro|yes|👍|✅)(\b|$)/i.test(resposta);
        const negou     = /^(nao|n|nope|errado|corrigir|recomecar|no|❌)(\b|$)/i.test(resposta);

        if (!confirmou && !negou) {
          await bot.sendMessage(msg.from, '⚠️ Por favor, responda *sim* para confirmar ou *não* para corrigir os dados.');
          return;
        }

        if (negou) {
          // Recomeça o onboarding do zero
          StateManager.setState(phone, 'ONBOARDING_NOME', {});
          await bot.sendMessage(msg.from,
            `Sem problema! Vamos recomeçar. 😊\n\n` +
            `👤 Por favor, digite novamente seu *nome completo*:`
          );
          return;
        }

        // Confirmou — cria a conta
        const dataCadastro = {
          phone,
          nome: ctx.data.nome,
          data_nasc: ctx.data.data_nasc,
          email: ctx.data.email
        };

        try {
          await bot.sendMessage(msg.from, '⏳ Criando seu cadastro...');
          const res = await axios.post(`${API}/onboarding/cadastrar`, dataCadastro);
          const userId = res.data.id;

          StateManager.setState(phone, 'ONBOARDING_OAUTH', { userId });

          const botPhone = msg.to.replace('@c.us', '');
          const authRes = await axios.post(`${API}/onboarding/auth_url`, { phone, botPhone });
          await bot.sendMessage(msg.from,
            `✅ *Cadastro realizado com sucesso!*\n\n` +
            `📌 Agora precisamos conectar sua conta do *Google Agenda* para gerenciar seus compromissos.\n\n` +
            `🔗 Acesse o link abaixo para autorizar:\n${authRes.data.url}\n\n` +
            `_Após autorizar, a página solicitará para abrir o WhatsApp e enviar a mensagem de confirmação pré-preenchida. Basta clicar em Enviar!_`
          );
        } catch (err) {
          console.error('[Onboarding/cadastrar]', err.message);
          const errorMsg = err.response?.data?.erro || 'Erro ao realizar cadastro.';

          if (errorMsg.includes('e-mail') || errorMsg.includes('email')) {
            // E-mail duplicado — volta para pedir novo e-mail
            StateManager.setState(phone, 'ONBOARDING_EMAIL', {
              nome: ctx.data.nome,
              data_nasc: ctx.data.data_nasc
            });
            await bot.sendMessage(msg.from,
              `⚠️ ${errorMsg}\n\nPor favor, informe outro *e-mail*:`
            );
          } else {
            await bot.sendMessage(msg.from, `😕 ${errorMsg} Tente novamente mais tarde.`);
            StateManager.clearState(phone);
          }
        }
        break;
      }

      case 'ONBOARDING_OAUTH': {
        try {
          await bot.sendMessage(msg.from, '⏳ Verificando e conectando sua conta...');
          const res = await axios.post(`${API}/onboarding/confirmar_code`, {
            phone,
            code: text,
            userId: ctx.data.userId
          });

          StateManager.clearState(phone);
          await bot.sendMessage(msg.from,
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
        } catch (err) {
          console.error('[Onboarding/confirmar_code]', err.message);
          const errorMsg = err.response?.data?.erro || 'Código ou URL inválido.';
          await bot.sendMessage(msg.from,
            `⚠️ ${errorMsg}\n\n` +
            `Tente acessar o link novamente e cole a *URL completa* de retorno aqui:`
          );
        }
        break;
      }
    }
  }
}

module.exports = OnboardingCommand;
