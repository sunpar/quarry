import { useState, type KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface PromptBoxProps {
  running: boolean;
  /** The kernel is dead: steps would fail until a restart. */
  kernelDead?: boolean;
  onSubmit: (prompt: string) => Promise<unknown>;
  onStop: () => void;
}

export function PromptBox({
  running,
  kernelDead = false,
  onSubmit,
  onStop,
}: PromptBoxProps) {
  const [text, setText] = useState("");
  const locked = running || kernelDead;
  const submit = () => {
    const prompt = text.trim();
    if (prompt === "" || locked) return;
    // Keep the text if the submit is refused; the caller shows that error.
    onSubmit(prompt).then(
      () => setText(""),
      () => undefined,
    );
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      submit();
    }
  };
  return (
    <div className="flex items-end gap-3 border-t border-border bg-card px-8 py-4">
      <Textarea
        value={text}
        disabled={locked}
        placeholder={
          running
            ? "Working on the last step"
            : kernelDead
              ? "Restart the kernel to continue"
              : "Ask about the data"
        }
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        rows={2}
        className="max-w-[880px] flex-1 resize-none font-sans"
      />
      {running ? (
        <Button variant="outline" onClick={onStop}>
          Stop
        </Button>
      ) : (
        <Button disabled={kernelDead} onClick={submit}>
          Run
        </Button>
      )}
    </div>
  );
}
