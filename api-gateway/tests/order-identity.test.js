const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const http = require('node:http');
const test = require('node:test');
const jwt = require('jsonwebtoken');

function listen(handler) {
  const server = http.createServer(handler);
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
}

function close(server) {
  return new Promise((resolve) => server.close(resolve));
}

test('assistant receives only gateway-verified identity headers', async () => {
  const assistant = await listen((req, res) => {
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({ userId: req.headers['x-user-id'] || '', role: req.headers['x-user-role'] || '' }));
  });
  const auth = await listen((req, res) => {
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({ user: { id: 'buyer-1', role: 'buyer' } }));
  });
  const portServer = await listen((_req, res) => res.end());
  const gatewayPort = portServer.address().port;
  await close(portServer);
  const gateway = spawn(process.execPath, ['server.js'], {
    cwd: __dirname + '/..',
    env: {
      ...process.env,
      PORT: String(gatewayPort),
      CHATBOT_SERVICE_URL: `http://127.0.0.1:${assistant.address().port}`,
      AUTH_SERVICE_URL: `http://127.0.0.1:${auth.address().port}`,
      JWT_SECRET: 'order-identity-test',
    },
    stdio: 'ignore',
  });
  const url = `http://127.0.0.1:${gatewayPort}/assistant/chat`;
  async function request(headers) {
    for (let attempt = 0; attempt < 40; attempt += 1) {
      try {
        const response = await fetch(url, {
          method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: '{}',
        });
        return { status: response.status, body: await response.json() };
      } catch {
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
    }
    throw new Error('Gateway did not start');
  }
  try {
    const anonymous = await request({ 'x-user-id': 'victim', 'x-user-role': 'buyer' });
    assert.equal(anonymous.status, 200);
    assert.deepEqual(anonymous.body, { userId: '', role: '' });

    const token = jwt.sign({ id: 'buyer-1', role: 'buyer' }, 'order-identity-test');
    const verified = await request({
      Authorization: `Bearer ${token}`, 'x-user-id': 'victim', 'x-user-role': 'admin',
    });
    assert.equal(verified.status, 200);
    assert.deepEqual(verified.body, { userId: 'buyer-1', role: 'buyer' });
  } finally {
    gateway.kill();
    await Promise.all([close(assistant), close(auth)]);
  }
});
