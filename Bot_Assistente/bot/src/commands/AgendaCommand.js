const { Intent } = require('../models/enums');
const axios = require('axios');
const API = process.env.PYTHON_API || 'http://localhost:8080';

class AgendaCommand {
  canHandle(intent) {
    return [Intent.AGENDAR, Intent.VER_HOJE, Intent.VER_SEMANA, Intent.VER_LIVRE, Intent.CANCELAR_EVENTO].includes(intent);
  }

  async execute(msg, ctx, bot, intent) {
    const phone = msg.from.replace('@c.us', '');
    const msgs = {
      [Intent.VER_HOJE]:        '📅 Buscando agenda de hoje...',
      [Intent.VER_SEMANA]:      '📅 Buscando agenda da semana...',
      [Intent.VER_LIVRE]:       '🕐 Verificando horários livres...',
      [Intent.AGENDAR]:         '⏳ Interpretando agendamento...',
      [Intent.CANCELAR_EVENTO]: '🗑️ Procurando evento...',
    };
    await bot.sendMessage(msg.from, msgs[intent]);
    try {
      const endpoints = {
        [Intent.VER_HOJE]:        ['/agenda/hoje',    { phone }],
        [Intent.VER_SEMANA]:      ['/agenda/semana',  { phone }],
        [Intent.VER_LIVRE]:       ['/agenda/livres',  { phone }],
        [Intent.AGENDAR]:         ['/agenda/agendar', { phone, texto: msg.body }],
        [Intent.CANCELAR_EVENTO]: ['/agenda/cancelar',{ phone, texto: msg.body }],
      };
      const [path, body] = endpoints[intent];
      const res = await axios.post(`${API}${path}`, body);
      await bot.sendMessage(msg.from, res.data.texto);
      if (res.data.pendente && res.data.estado) {
        const StateManager = require('../models/StateManager');
        StateManager.setState(phone, res.data.estado, res.data.dados || {});
      }
    } catch (err) {
      console.error('[Agenda]', err.message);
      const txt = err.code === 'ECONNREFUSED'
        ? '⚠️ Servidor Python offline. Inicie o webhook.py.'
        : '😕 Erro ao acessar agenda. Tente novamente.';
      await bot.sendMessage(msg.from, txt);
    }
  }
}

module.exports = AgendaCommand;
