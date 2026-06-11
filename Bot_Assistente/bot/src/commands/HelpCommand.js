const { Intent } = require('../models/enums');

class HelpCommand {
  canHandle(intent) { return intent === Intent.AJUDA || intent === Intent.DESCONHECIDO; }

  async execute(msg, ctx, bot) {
    await bot.sendMessage(msg.from,
`🤖 *SecretarIA — Menu de ajuda:*

📅 *Agenda*
• _"agendar reunião sexta às 15h"_
• _"ver agenda hoje"_
• _"o que tenho essa semana"_
• _"quando estou livre amanhã"_
• _"cancelar reunião das 15h"_

💰 *Financeiro*
• _"gastei 45 reais no almoço"_
• _"ver meus gastos do mês"_
• _"definir teto de 2000 reais"_
• 📸 _Mande foto de recibo/nota fiscal_

🎙️ *Áudio*
• Mande um áudio com qualquer pedido!

❓ Digite _ajuda_ para ver este menu.`
    );
  }
}

module.exports = HelpCommand;
