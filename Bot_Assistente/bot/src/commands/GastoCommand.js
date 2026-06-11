const { Intent } = require('../models/enums');
const StateManager = require('../models/StateManager');
const axios = require('axios');
const API = process.env.PYTHON_API || 'http://localhost:8080';

class GastoCommand {
  canHandle(intent) {
    return [Intent.REGISTRAR_GASTO, Intent.VER_FINANCAS, Intent.DEFINIR_TETO].includes(intent);
  }

  async execute(msg, ctx, bot, intent, dados) {
    const phone = msg.from.replace('@c.us', '');
    try {
      if (intent === Intent.REGISTRAR_GASTO) {
        if (!dados.valor || dados.valor <= 0) {
          StateManager.setState(phone, 'AGUARDANDO_VALOR_GASTO', { descricao: dados.descricao || msg.body });
          await bot.sendMessage(msg.from, '💬 Qual foi o valor do gasto?\n_(ex: 45.90)_');
          return;
        }
        StateManager.setState(phone, 'AGUARDANDO_CONFIRMAR_GASTO', { valor: dados.valor, descricao: dados.descricao });
        await bot.sendMessage(msg.from,
          `💰 Confirmar gasto?\n\n📝 *${dados.descricao}*\n💵 R$ ${dados.valor.toFixed(2)}\n\n_(sim / não)_`
        );
      } else if (intent === Intent.VER_FINANCAS) {
        await bot.sendMessage(msg.from, '📊 Buscando seus gastos...');
        const res = await axios.post(`${API}/financeiro/resumo`, { phone });
        await bot.sendMessage(msg.from, res.data.texto);
      } else if (intent === Intent.DEFINIR_TETO) {
        const m = msg.body.match(/r?\$?\s*(\d+(?:[.,]\d{1,2})?)/i);
        const valor = m ? parseFloat(m[1].replace(',', '.')) : null;
        if (!valor) {
          StateManager.setState(phone, 'AGUARDANDO_VALOR_TETO', {});
          await bot.sendMessage(msg.from, '💬 Qual o valor do teto mensal?\n_(ex: 3000)_');
          return;
        }
        const res = await axios.post(`${API}/financeiro/teto`, { phone, valor });
        await bot.sendMessage(msg.from, res.data.texto);
      }
    } catch (err) {
      console.error('[Gasto]', err.message);
      await bot.sendMessage(msg.from, err.code === 'ECONNREFUSED'
        ? '⚠️ Servidor Python offline. Inicie o webhook.py.'
        : '😕 Erro ao processar. Tente novamente.');
    }
  }
}

module.exports = GastoCommand;
