/**
 * IntentParser — classifica intenção de TEXTO localmente.
 * Zero chamadas ao Gemini.
 */
const { Intent } = require('../models/enums');

const PADROES = [
  // ── Confirmação e Negação (máxima prioridade) ────────────────────────
  { intent: Intent.CONFIRMAR, regex: /^(sim|s|ok|pode|confirma|certo|claro|yes|👍|✅)\b/i },
  { intent: Intent.NEGAR,     regex: /^(não|nao|n|cancela|para|chega|\bno\b|❌)/i },

  // ── Agendamento — verbo de ação explícito (alta prioridade) ──────────
  // Cobre: "agende", "marque", "crie", "coloca", "quero agendar", "preciso marcar", etc.
  {
    intent: Intent.AGENDAR,
    regex: /\b(agendar?|marcar?|criar?|colocar?|agende|marque|crie|coloca|quero marcar|quero agendar|preciso marcar|preciso agendar)\b/i
  },

  // ── Agendamento — consulta/tipo de evento implícito ──────────────────
  // Cobre: "dentista", "médico", "consulta", "reunião com X amanhã às 15h"
  {
    intent: Intent.AGENDAR,
    regex: /\b(dentista|m[eé]dico|consulta|cirurgi[ao]|exame|check-?up)\b.*(amanh[aã]|hoje|segunda|ter[çc]a|quarta|quinta|sexta|s[aá]bado|domingo|\d{1,2}[\/h:])/i
  },
  {
    intent: Intent.AGENDAR,
    regex: /\b(dentista|m[eé]dico|consulta|cirurgi[ao]|exame)\b.*\b(às|as|hora)\b.*\d/i
  },

  // ── Agendamento — dias da semana com horário (sem verbo) ─────────────
  // Cobre: "reunião com João sexta às 15h", "almoço amanhã às 12h"
  {
    intent: Intent.AGENDAR,
    regex: /\b(reuni[aã]o|evento|compromiss|call|almo[cç]o|jantar|confraterniza[cç][aã]o)\b.*(amanh[aã]|hoje|segunda|ter[çc]a|quarta|quinta|sexta|s[aá]bado|domingo|\d{1,2}[\/h:])/i
  },

  // ── Ver Agenda Hoje ───────────────────────────────────────────────────
  {
    intent: Intent.VER_HOJE,
    regex: /\b(agenda|compromiss|reuni[aã]o|evento).*(hoje)\b|\b(hoje).*(agenda|compromiss)\b|(ver|mostr|qual|tem).*(agenda|compromiss|reuni[aã]o).*(hoje|\bdia\b)/i
  },

  // ── Ver Agenda Semana ─────────────────────────────────────────────────
  {
    intent: Intent.VER_SEMANA,
    regex: /\b(agenda|compromiss|reuni[aã]o|evento).*(semana)\b|\bsemana\b.*(agenda|compromiss)/i
  },

  // ── Ver Horários Livres ───────────────────────────────────────────────
  {
    intent: Intent.VER_LIVRE,
    regex: /\b(hor[aá]rio|quando).*(livr|dispon)|\b(livr|dispon).*(hoje|amanh[aã]|semana)/i
  },

  // ── Cancelar Evento ───────────────────────────────────────────────────
  {
    intent: Intent.CANCELAR_EVENTO,
    regex: /\b(cancel|remov|delet|apag|desmarcar?).*(reuni[aã]o|evento|compromiss|agenda|dentista|m[eé]dico|consulta)/i
  },

  // ── Finanças: Registrar Gasto ─────────────────────────────────────────
  {
    intent: Intent.REGISTRAR_GASTO,
    regex: /\b(gastei|paguei|comprei|despesa|gasto|pago|gastou)\b.*(\d)|^\s*r?\$\s*\d/i
  },

  // ── Finanças: Ver Resumo ──────────────────────────────────────────────
  {
    intent: Intent.VER_FINANCAS,
    regex: /\b(ver|mostr|quanto|resumo|extrato|relat).*(gast|financ|despesa|teto)\b|\b(financ|gast|despesa).*(m[eê]s|semana|hoje)\b/i
  },

  // ── Finanças: Definir Teto ────────────────────────────────────────────
  {
    intent: Intent.DEFINIR_TETO,
    regex: /\b(definir?|colocar?|setar?|configur).*(teto|limite)\b|\bteto\b.*(r\$|\d)/i
  },

  // ── Ajuda / Saudação ─────────────────────────────────────────────────
  {
    intent: Intent.AJUDA,
    regex: /\b(ajuda|help|oi|ol[aá]|bom dia|boa tarde|boa noite|menu|op[cç][oõ]|o que (faz|pod))\b/i
  },
];

function extrairValor(texto) {
  const m = texto.match(/r?\$?\s*(\d+(?:[.,]\d{1,2})?)/i);
  return m ? parseFloat(m[1].replace(',', '.')) : null;
}

function extrairDescricao(texto) {
  return texto
    .replace(/^(gastei|paguei|comprei|gasto de|despesa de)/i, '')
    .replace(/r?\$\s*\d+[.,]?\d*/gi, '')
    .replace(/\s+/g, ' ').trim().substring(0, 60) || 'Gasto via WhatsApp';
}

function classificar(texto) {
  const t = texto.trim();
  for (const { intent, regex } of PADROES) {
    if (regex.test(t)) {
      const dados = {};
      if (intent === Intent.REGISTRAR_GASTO) {
        dados.valor     = extrairValor(t);
        dados.descricao = extrairDescricao(t);
      }
      return { intent, dados };
    }
  }
  return { intent: Intent.DESCONHECIDO, dados: {} };
}

module.exports = { classificar, extrairValor };
