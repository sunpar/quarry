import { transpile } from "../src/runtime/loader.ts";

const chunks: Buffer[] = [];
process.stdin.on("data", (chunk: Buffer) => chunks.push(chunk));
process.stdin.on("end", () => {
  const source = Buffer.concat(chunks).toString("utf8");
  try {
    transpile(source);
  } catch (error) {
    process.stderr.write(
      error instanceof Error ? error.message : String(error),
    );
    process.exitCode = 1;
  }
});
