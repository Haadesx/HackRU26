import Card from "../../components/Card";
import EmptyState from "../../components/EmptyState";
import Button from "../../components/Button";
import PillBottle from "./PillBottle";

export default function SupplyShelf({ meds, now, thresholds, onOpen }) {
  return (
    <Card as="section" aria-labelledby="supply-h">
      <h2 id="supply-h" className="text-xl font-bold">Supply for the next 30 days</h2>
      <p className="mb-5 max-w-[70ch] text-ink-soft">
        Each bottle shows how many days of pills Rosa has left. A full bottle is 30 days or more. Tap a cap to see everything about that medication.
      </p>
      {meds.length === 0 ? (
        <EmptyState action={<Button to="/scan">Scan a bottle</Button>}>No medications yet. Scan a bottle to add the first one.</EmptyState>
      ) : (
        <div className="flex items-end gap-5 pb-2">
          <div aria-hidden="true" className="hidden flex-none flex-col items-end pb-[38px] text-[15px] font-bold text-ink-soft sm:flex">
            <span className="h-[34px] leading-[34px]">Days left</span>
            <span className="h-[26px] leading-[26px]">Runs out</span>
          </div>
          <ul className="flex flex-1 flex-wrap items-end justify-center gap-6 sm:justify-around">
            {meds.map((m) => (
              <PillBottle key={m.id} med={m} now={now} thresholds={thresholds} onOpen={() => onOpen(m.id)} />
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}
