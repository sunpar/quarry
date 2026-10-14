// Test processes may use loopback and Unix sockets, never live services.
const net = require("node:net");
const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...input) {
  const args = Array.isArray(input[0]) ? input[0] : input;
  const options =
    typeof args[0] === "object"
      ? args[0]
      : {
          port: args[0],
          host: typeof args[1] === "string" ? args[1] : undefined,
        };
  const pipe =
    options.path || (typeof args[0] === "string" && !/^\d+$/.test(args[0]));
  const host = options.host ?? "localhost";
  if (!pipe && !["localhost", "127.0.0.1", "::1", "[::1]"].includes(host))
    throw new Error(`External network disabled in local tests: ${host}`);
  return connect.apply(this, input);
};
