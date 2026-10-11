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
    <div className="flex flex-col gap-8 xl:gap-10">
      <header className="flex flex-wrap items-end justify-between gap-6">
        <StatusHeadline summary={summary} patient={data.patient} now={now} />
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" size="lg" to="/scan">Add medication</Button>
          {summary.focus && <Button size="lg" onClick={() => setOpenId(summary.focus.id)}>See {summary.focus.name}</Button>}
        </div>
      </header>

      {/* Wide screens: the supply shelf is the main read, today's doses a side panel. */}
      <div className="grid items-start gap-8 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] xl:gap-10">
        <SupplyShelf meds={meds} now={now} thresholds={t} onOpen={setOpenId} />
        <TodayDoses data={data} />
      </div>

      <div className="grid gap-7 md:grid-cols-2 xl:grid-cols-3">
        {pending.length > 0 && (
          <section aria-labelledby="help-h" className="flex flex-col gap-3">
            <h2 id="help-h" className="text-xl font-bold">Needs your help</h2>
            {pending.map((s) => <NeedsHelpCard key={s.id} scan={s} now={now} />)}
          </section>
        )}
        <AlertFeed alerts={data.alerts} now={now} />
        <MistakesCaught events={data.events} now={now} />
      </div>

      <p className="max-w-[75ch] border-t border-line pt-4 text-[15px] text-ink-soft">
        Camera images never leave {data.patient.name}'s home. This page shows only what MedCheck read from labels and the doses it logged.
      </p>

      <Dialog open={!!openMed} onClose={() => setOpenId(null)} label={openMed ? `${openMed.name} details` : "Medication"}>
        {openMed && <MedicationPanel key={openMed.id} medId={openMed.id} onClose={() => setOpenId(null)} />}
      </Dialog>
    </div>
  );
}
