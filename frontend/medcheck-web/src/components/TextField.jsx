const STATE = {
  filled: "",
  unsure: "!border-low-line bg-low-tint",
  missing: "!border-urgent-line bg-urgent-tint",
};

/** Capsule text input with an optional filled / unsure / missing state from a label scan. */
export default function TextField({ id, label, state = "filled", note, className = "", ...rest }) {
  const noteId = note ? `${id}-note` : undefined;
  return (
    <label htmlFor={id} className={`flex flex-col gap-1.5 ${className}`}>
      <span className="font-bold">{label}</span>
      <input id={id} className={`field ${STATE[state]}`} aria-describedby={noteId} aria-invalid={state === "missing" || undefined} {...rest} />
      {note && (
        <span id={noteId} className={`text-sm font-bold ${state === "missing" ? "text-urgent" : "text-low"}`}>{note}</span>
      )}
    </label>
  );
}
