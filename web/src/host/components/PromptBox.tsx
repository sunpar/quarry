import { useState, type KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface PromptBoxProps {
  running: boolean;
  onSubmit: (prompt: string) => Promise<unknown>;
  onStop: () => void;
}

export function PromptBox({ running, onSubmit, onStop }: PromptBoxProps) {
  const [text, setText] = useState("");
  const submit = () => {
    const prompt = text.trim();
    if (prompt === "" || running) return;
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
        disabled={running}
        placeholder={
          running ? "Working on the last step" : "Ask about the data"
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
        <Button onClick={submit}>Run</Button>
      )}
    </div>
  );
}
