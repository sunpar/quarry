import { transform } from "sucrase";

const chunks: Buffer[] = [];
process.stdin.on("data", (chunk: Buffer) => chunks.push(chunk));
process.stdin.on("end", () => {
  const source = Buffer.concat(chunks).toString("utf8");
  try {
    transform(source, {
      transforms: ["typescript", "jsx", "imports"],
      jsxRuntime: "automatic",
    });
  } catch (error) {
    process.stderr.write(
      error instanceof Error ? error.message : String(error),
    );
    process.exit(1);
  }
});
