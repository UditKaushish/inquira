import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { ArrowUp, Square } from "lucide-react";
import clsx from "clsx";

export interface ComposerHandle {
  focus: () => void;
  setValue: (v: string) => void;
}

export const Composer = forwardRef<
  ComposerHandle,
  { onSubmit: (q: string) => void; busy?: boolean; onStop?: () => void; large?: boolean; placeholder?: string; disabled?: boolean }
>(function Composer({ onSubmit, busy, onStop, large, placeholder, disabled }, ref) {
  const [value, setValue] = useState("");
  const ta = useRef<HTMLTextAreaElement>(null);

  useImperativeHandle(ref, () => ({ focus: () => ta.current?.focus(), setValue }));

  useEffect(() => {
    const el = ta.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [value]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        ta.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const submit = () => {
    const q = value.trim();
    if (!q || busy || disabled) return;
    onSubmit(q);
    setValue("");
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className={clsx(
        "flex items-end gap-2 rounded-xl bg-surface p-2 hairline transition-shadow duration-150",
        "focus-within:border-accent/60 focus-within:ring-4 focus-within:ring-accent/10",
        large && "p-3",
      )}
    >
      <label htmlFor="composer" className="sr-only">
        Ask a question about your data
      </label>
      <textarea
        id="composer"
        ref={ta}
        rows={1}
        value={value}
        disabled={disabled}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
        placeholder={placeholder ?? "Ask anything about your data…"}
        className={clsx(
          "min-h-[36px] flex-1 resize-none bg-transparent px-2 py-1.5 text-text placeholder:text-muted/70 focus:outline-none",
          large ? "text-[15px]" : "text-sm",
        )}
      />
      {busy && onStop ? (
        <button type="button" onClick={onStop} aria-label="Stop" className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-surface-2 text-text hover:bg-border">
          <Square className="h-3.5 w-3.5 fill-current" />
        </button>
      ) : (
        <button
          type="submit"
          aria-label="Ask"
          disabled={!value.trim() || busy || disabled}
          className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-accent text-accent-fg transition-opacity duration-150 disabled:opacity-30"
        >
          <ArrowUp className="h-4 w-4" />
        </button>
      )}
    </form>
  );
});
