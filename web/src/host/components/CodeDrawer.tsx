import { useState } from "react";
import { Button } from "@/components/ui/button";

export function CodeDrawer({ code }: { code: string }) {
  const [open, setOpen] = useState(false);
  if (code.trim() === "") return null;
  return (
    <div>
      <Button
        variant="ghost"
        size="xs"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        Code
      </Button>
      {open && (
        <pre className="mt-1 overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs leading-relaxed">
          {code}
        </pre>
      )}
    </div>
  );
}
