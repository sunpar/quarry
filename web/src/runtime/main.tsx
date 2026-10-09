import { isHostMessage } from "@/shared/bridge-types";
import { createRuntime } from "./mount";
import "./index.css";

const root = document.getElementById("root");
if (root === null) throw new Error("missing #root");

const runtime = createRuntime(
  (message) => window.parent.postMessage(message, "*"),
  root,
);

window.addEventListener("message", (event: MessageEvent<unknown>) => {
  if (event.source !== window.parent) return;
  if (!isHostMessage(event.data)) return;
  runtime.handle(event.data);
});
