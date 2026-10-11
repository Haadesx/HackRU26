import { useState } from "react";
import Button from "../../components/Button";
import Dialog from "../../components/Dialog";
import { useAppState } from "../../state/AppState";
import { sortByUrgency } from "../../lib/inventory";
import StatusHeadline, { summarize } from "./StatusHeadline";
import SupplyShelf from "./SupplyShelf";
import NeedsHelpCard from "./NeedsHelpCard";
import TodayDoses from "./TodayDoses";
import AlertFeed from "./AlertFeed";
import MistakesCaught from "./MistakesCaught";
import MedicationPanel from "./MedicationPanel";

export default function HomePage() {
  const { data } = useAppState();
  const [openId, setOpenId] = useState(null);
  const now = new Date(data.now);
  const t = data.settings.thresholds;
  const meds = sortByUrgency(data.medications);
  const summary = summarize(meds, t);
  const pending = data.scans.filter((s) => s.status === "needs_caregiver");
  const openMed = data.medications.find((m) => m.id === openId);

  return (
    <div className="flex flex-col gap-9">
      <header className="flex flex-wrap items-end justify-between gap-6">
        <StatusHeadline summary={summary} patient={data.patient} now={now} />
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" size="lg" to="/scan">Add medication</Button>
          {summary.focus && <Button size="lg" onClick={() => setOpenId(summary.focus.id)}>See {summary.focus.name}</Button>}
        </div>
      </header>

      <SupplyShelf meds={meds} now={now} thresholds={t} onOpen={setOpenId} />

      <div className="grid items-start gap-9 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
        <TodayDoses data={data} />
        <aside className="flex flex-col gap-7">
          {pending.length > 0 && (
            <section aria-labelledby="help-h" className="flex flex-col gap-3">
              <h2 id="help-h" className="text-xl font-bold">Needs your help</h2>
              {pending.map((s) => <NeedsHelpCard key={s.id} scan={s} now={now} />)}
            </section>
          )}
          <AlertFeed alerts={data.alerts} now={now} />
          <MistakesCaught events={data.events} now={now} />
          <p className="border-t border-line pt-4 text-[15px] text-ink-soft">
            Camera images never leave {data.patient.name}'s home. This page shows only what MedCheck read from labels and the doses it logged.
          </p>
        </aside>
      </div>

      <Dialog open={!!openMed} onClose={() => setOpenId(null)} label={openMed ? `${openMed.name} details` : "Medication"}>
        {openMed && <MedicationPanel key={openMed.id} medId={openMed.id} onClose={() => setOpenId(null)} />}
      </Dialog>
    </div>
  );
}
