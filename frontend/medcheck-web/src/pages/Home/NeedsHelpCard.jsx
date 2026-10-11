import Button from "../../components/Button";
import { relativeDay } from "../../lib/format";

export default function NeedsHelpCard({ scan, now }) {
  const missing = Object.values(scan.fields).filter((f) => f.state !== "filled").length;
  const name = scan.fields.name.value || "a new medication";
  return (
    <div className="flex flex-col gap-2 rounded-2xl bg-mist p-4 shadow-[inset_0_0_0_2px_#9CC3EC]">
      <strong className="text-navy">Finish adding {name}</strong>
      <span>Rosa scanned a new bottle, but some details are missing. She couldn't add them by voice.</span>
      <Button to={`/scan/${scan.id}/verify`} className="self-start">Fill in {missing} {missing === 1 ? "detail" : "details"}</Button>
      <span className="text-sm text-ink-soft">{relativeDay(scan.history.at(-1)?.at || scan.created_at, now)}</span>
    </div>
  );
}
