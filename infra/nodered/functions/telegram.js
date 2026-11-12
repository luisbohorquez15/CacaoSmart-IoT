// Notificación de alertas warning/critical a Telegram (opcional: TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en .env)
const token = env.get('TELEGRAM_BOT_TOKEN'), chat = env.get('TELEGRAM_CHAT_ID');
if (!token || !chat) return null;
const a = typeof msg.payload === 'string' ? JSON.parse(msg.payload) : msg.payload;
if (!['warning', 'critical'].includes(a.severity)) return null;
const dev = msg.topic.split('/')[3];
const icon = a.severity === 'critical' ? '🚨' : '⚠️';
return {
  url: `https://api.telegram.org/bot${token}/sendMessage`, method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  payload: { chat_id: chat, text: `${icon} CacaoSmart · ${dev.toUpperCase()}\n${a.msg}` }
};
