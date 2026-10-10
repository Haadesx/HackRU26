import { useParams } from "react-router-dom";
import Button from "../../components/Button";
import { useAppState } from "../../state/AppState";
import { daysLeft } from "../../lib/inventory";
import { fmtSlot } from "../../lib/format";

export default function AddedPage() {
  const { medId } = useParams();
  const { data } = useAppState();
  const med = data.medications.find((m) => m.id === Number(medId));
  if (!med) return <p className="text-ink-soft">That medication was added. <Button to="/" variant="secondary">Back to home</Button></p>;
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center gap-5 py-16 text-center">
      <span aria-hidden="true" className="flex h-[88px] w-[88px] items-center justify-center rounded-full bg-gradient-to-br from-ok-pill to-ok-fill">
        <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="#22613B" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
      </span>
      <h1 className="text-[38px] font-bold leading-tight">{med.name} is added</h1>
      <p className="text-ink-soft">Rosa heard &ldquo;{med.name} is all set&rdquo; on her wearable. Her first reminder is at {fmtSlot(med.schedule_times[0])}.</p>
      <div className="card flex w-full flex-wrap justify-between gap-4 p-5 text-left">
        <span><strong>{med.name} {med.strength}</strong><br /><span className="text-ink-soft">{med.quantity_start} tablets, lasts about {Math.floor(daysLeft(med))} days</span></span>
      </div>
      <div className="flex flex-wrap justify-center gap-3">
        <Button variant="secondary" size="lg" to="/scan">Scan another bottle</Button>
        <Button size="lg" to="/">Back to home</Button>
      </div>
    </div>
  );
}
