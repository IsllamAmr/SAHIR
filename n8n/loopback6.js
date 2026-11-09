// Forwards [::1]:5678 to 127.0.0.1:5678 so http://localhost:5678 works without a delay.
// On this laptop "localhost" resolves to ::1 first; n8n itself only listens on 127.0.0.1.
// Both addresses are loopback, so n8n stays reachable from this laptop only.
const net = require('net');
const PORT = 5678;
net.createServer((client) => {
  const upstream = net.connect(PORT, '127.0.0.1');
  client.pipe(upstream).pipe(client);
  const close = () => { client.destroy(); upstream.destroy(); };
  client.on('error', close);
  upstream.on('error', close);
}).on('error', (e) => console.error('loopback6:', e.message))
  .listen({ port: PORT, host: '::1', ipv6Only: true }, () => console.log('localhost (::1) forwarder on [::1]:' + PORT));
