const { Intent } = require('../models/enums');
const StateManager = require('../models/StateManager');
const axios = require('axios');
const API = process.env.PYTHON_API || 'http://localhost:8080';

const ESTADOS_ATIVOS = [
  'AGUARDANDO_CONFIRMAR_GASTO',
  'AGUARDANDO_VALOR_GASTO',
  'AGUARDANDO_VALOR_TETO',
  'AGUARDANDO_CONFIRMAR_AGENDA',
  'EXCLUIR_CONTA_CONFIRMANDO',
];

class ConfirmCommand {
  canHandle(intent, ctx) { return ESTADOS_ATIVOS.includes(ctx.state); }

  async execute(msg, ctx, bot, intent) {
    const phone = msg.from.replace('@c.us', '');
    const texto = msg.body.trim();
    try {
      if (ctx.state === 'AGUARDANDO_CONFIRMAR_GASTO') {
        if (intent === Intent.CONFIRMAR) {
          const { valor, descricao, categoria } = ctx.data;
          const res = await axios.post(`${API}/financeiro/registrar`, { phone, valor, descricao, categoria: categoria || 'Outros' });
          StateManager.clearState(phone);
          await bot.sendMessage(msg.from, res.data.texto);
        } else if (intent === Intent.NEGAR) {
          StateManager.clearState(phone);
          await bot.sendMessage(msg.from, '❌ Gasto cancelado.');
        } else {
          await bot.sendMessage(msg.from, '⚠️ Responda *sim* para confirmar e registrar o gasto ou *não* para cancelar.');
        }

      } else if (ctx.state === 'AGUARDANDO_VALOR_GASTO') {
        const valor = parseFloat(texto.replace(',', '.').replace(/[^\d.]/g, ''));
        if (isNaN(valor) || valor <= 0) {
          await bot.sendMessage(msg.from, '⚠️ Valor inválido. Ex: _45.90_'); return;
        }
        const descricao = ctx.data.descricao || 'Gasto via WhatsApp';
        StateManager.setState(phone, 'AGUARDANDO_CONFIRMAR_GASTO', { valor, descricao });
        await bot.sendMessage(msg.from,
          `💰 Confirmar gasto?\n\n📝 *${descricao}*\n💵 R$ ${valor.toFixed(2)}\n\n_(sim / não)_`
        );

      } else if (ctx.state === 'AGUARDANDO_VALOR_TETO') {
        const valor = parseFloat(texto.replace(',', '.').replace(/[^\d.]/g, ''));
        if (isNaN(valor) || valor <= 0) {
          await bot.sendMessage(msg.from, '⚠️ Valor inválido. Ex: _3000_'); return;
        }
        const res = await axios.post(`${API}/financeiro/teto`, { phone, valor });
        StateManager.clearState(phone);
        await bot.sendMessage(msg.from, res.data.texto);

      } else if (ctx.state === 'AGUARDANDO_CONFIRMAR_AGENDA') {
        if (intent === Intent.CONFIRMAR) {
          const res = await axios.post(`${API}/agenda/confirmar`, { phone, evento: ctx.data.evento });
          StateManager.clearState(phone);
          await bot.sendMessage(msg.from, res.data.texto);
        } else if (intent === Intent.NEGAR) {
          StateManager.clearState(phone);
          await bot.sendMessage(msg.from, '❌ Agendamento cancelado.');
        } else {
          await bot.sendMessage(msg.from, '⚠️ Responda *sim* para confirmar o agendamento ou *não* para cancelar.');
        }

      } else if (ctx.state === 'EXCLUIR_CONTA_CONFIRMANDO') {
        if (intent === Intent.CONFIRMAR) {
          await bot.sendMessage(msg.from, '⏳ Excluindo sua conta...');
          const res = await axios.post(`${API}/onboarding/excluir`, { phone });
          StateManager.clearState(phone);
          if (res.data.sucesso) {
            await bot.sendMessage(msg.from,
              `✅ *Conta excluída com sucesso.*\n\n` +
              `Todos os seus dados foram removidos permanentemente.\n\n` +
              `Se quiser usar a SecretarIA novamente no futuro, basta me enviar uma mensagem que farei seu cadastro do início. 👋`
            );
          } else {
            await bot.sendMessage(msg.from, `⚠️ ${res.data.erro || 'Erro ao excluir conta. Tente novamente.'}`);
          }
        } else {
          StateManager.clearState(phone);
          await bot.sendMessage(msg.from, '✅ Cancelado! Sua conta foi *mantida*. 😊');
        }
      }

    } catch (err) {
      console.error('[Confirm]', err.message);
      StateManager.clearState(phone);
      await bot.sendMessage(msg.from, err.code === 'ECONNREFUSED'
        ? '⚠️ Servidor Python offline. Inicie o webhook.py.'
        : '😕 Erro. Estado reiniciado. Tente novamente.');
    }
  }
}

module.exports = ConfirmCommand;
