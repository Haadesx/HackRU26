import StatusBadge from "../../components/StatusBadge";
import { daysLeft, statusOf } from "../../lib/inventory";
import { greeting, plural } from "../../lib/format";

export function summarize(meds, thresholds) {
  const urgent = meds.filter((m) => statusOf(m, thresholds) === "urgent");
  const low = meds.filter((m) => statusOf(m, thresholds) === "low");
  if (urgent.length) {
    const m = urgent[0];
    const d = Math.floor(daysLeft(m));
    return {
      tone: "urgent",
      focus: m,
      text: d <= 0 ? `Rosa is out of ${m.name}.` : `${m.name} runs out in ${plural(d, "day")}.`,
      badge: m.refills_remaining === 0 ? "Urgent: no refills left" : "Urgent: refill now",
      sub: m.refills_remaining === 0
        ? `There are no refills left, so ${m.prescriber || "the doctor"} needs to send a new prescription.`
        : `Pick up a refill from ${m.pharmacy_name}.`,
    };
  }
  if (low.length) {
    return { tone: "low", focus: low[0], text: `${plural(low.length, "medication")} ${low.length > 1 ? "need" : "needs"} a refill this week.`, badge: "Refill soon" };
  }
  return { tone: "ok", text: "Every medication is stocked for at least a week." };
}

export default function StatusHeadline({ summary, patient, now }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-ink-soft">{greeting(now)}, {patient.caregiver}. Here's how {patient.name} is doing.</p>
      <h1 className="max-w-[22ch] text-[34px] font-bold leading-tight sm:text-[42px]">{summary.text}</h1>
      {summary.badge && <StatusBadge tone={summary.tone} className="self-start">{summary.badge}</StatusBadge>}
      {summary.sub && <p className="text-ink-soft">{summary.sub}</p>}
    </div>
  );
}
