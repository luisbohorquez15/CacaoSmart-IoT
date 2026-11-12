/**
 * Node-RED - CacaoSmart IoT (orquestador: APIs, motor de reglas y API REST)
 * Las credenciales del broker se inyectan desde el .env al arrancar (nunca quedan en el repo).
 */
const fs = require('fs');
let bcrypt;
try { bcrypt = require('/usr/src/node-red/node_modules/bcryptjs'); } catch (e) { bcrypt = null; }

fs.writeFileSync('/data/flows_cred.json', JSON.stringify({
  mqtt_broker: { user: process.env.MQTT_SERVICE_USER || 'service', password: process.env.MQTT_SERVICE_PASS || '' }
}));

const adminPass = process.env.NODERED_ADMIN_PASS || 'admin';

module.exports = {
  flowFile: 'flows.json',
  credentialSecret: false,
  uiPort: process.env.PORT || 1880,
  httpAdminRoot: '/nodered',          // editor:   https://<dominio>/nodered
  httpNodeRoot: '/',                  // API REST: https://<dominio>/api/...
  httpNodeCors: { origin: '*', methods: 'GET,POST' },
  adminAuth: bcrypt ? {
    type: 'credentials',
    users: [{ username: process.env.NODERED_ADMIN_USER || 'admin', password: bcrypt.hashSync(adminPass, 8), permissions: '*' }]
  } : undefined,
  contextStorage: { default: { module: 'localfilesystem' } },   // estado de reglas persistente (/data/context)
  functionExternalModules: false,
  logging: { console: { level: 'info', metrics: false, audit: false } },
  diagnostics: { enabled: false },
  editorTheme: {
    page: { title: 'CacaoSmart · Orquestador' },
    header: { title: 'CacaoSmart IoT · Node-RED' },
    projects: { enabled: false },
    tours: false
  }
};
