import { useEffect, useState } from "react";
import Button from "../../components/Button";
import Card from "../../components/Card";
import Toggle from "../../components/Toggle";
import TextField from "../../components/TextField";
import Notice from "../../components/Notice";
import Dialog from "../../components/Dialog";
import { api } from "../../api/client";
import { useAppState } from "../../state/AppState";

const SCOPE = { all: "All alerts", refills: "Refill alerts only" };

export default function SettingsPage() {
  const { data, run } = useAppState();
  const [s, setS] = useState(data.settings);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(null);
  const [adding, setAdding] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => setS(data.settings), [data.settings]);
  const dirty = JSON.stringify(s) !== JSON.stringify(data.settings);
  const set = (patch) => { setS({ ...s, ...patch }); setSaved(false); };
  const setT = (k, v) => set({ thresholds: { ...s.thresholds, [k]: Math.max(1, Number(v) || 1) } });

  const save = async (next = s) => {
    setBusy("save");
    try { await run(() => api.saveSettings(next)); setSaved(true); } finally { setBusy(null); }
  };

  const exportData = async () => {
    const blob = await api.exportData();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = "medcheck-data.json"; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="grid items-start gap-7 xl:grid-cols-2">
      <h1 className="text-[38px] font-bold leading-tight xl:col-span-2">Settings</h1>

      <Card as="section" aria-labelledby="people-h" className="flex flex-col gap-3">
        <div>
          <h2 id="people-h" className="text-xl font-bold">People who get texts</h2>
          <p className="max-w-[70ch] text-ink-soft">Only these people ever hear from MedCheck. {data.patient.name} chose them.</p>
        </div>
        <ul>
          {s.caregivers.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center justify-between gap-3 border-t border-line-soft py-3.5">
              <div><strong>{c.name}{c.you ? " (you)" : ""}</strong><div className="text-[15px] text-ink-soft">{c.phone}. {SCOPE[c.scope]}.</div></div>
              <label className="flex items-center gap-2">
                <span className="sr-only">Alerts for {c.name}</span>
                <select className="field w-auto" value={c.scope} onChange={(e) => set({ caregivers: s.caregivers.map((x) => x.id === c.id ? { ...x, scope: e.target.value } : x) })}>
                  <option value="all">All alerts</option>
                  <option value="refills">Refill alerts only</option>
                </select>
              </label>
            </li>
          ))}
        </ul>
        {adding ? (
          <form className="grid gap-3 rounded-2xl bg-page p-4 sm:grid-cols-2" onSubmit={(e) => {
            e.preventDefault();
            if (!adding.name.trim() || !adding.phone.trim()) return;
            set({ caregivers: [...s.caregivers, { id: Date.now(), name: adding.name.trim(), phone: adding.phone.trim(), scope: "all" }] });
            setAdding(null);
          }}>
            <TextField id="cg-name" label="Name" value={adding.name} onChange={(e) => setAdding({ ...adding, name: e.target.value })} autoFocus />
            <TextField id="cg-phone" label="Mobile number" type="tel" value={adding.phone} onChange={(e) => setAdding({ ...adding, phone: e.target.value })} />
            <div className="flex justify-end gap-2.5 sm:col-span-2">
              <Button variant="secondary" onClick={() => setAdding(null)}>Cancel</Button>
              <Button type="submit">Add person</Button>
            </div>
          </form>
        ) : (
          <Button className="self-start" onClick={() => setAdding({ name: "", phone: "" })}>Add a person</Button>
        )}
      </Card>

      <Card as="section" aria-labelledby="when-h" className="flex flex-col gap-4">
        <div>
          <h2 id="when-h" className="text-xl font-bold">When to text you</h2>
          <p className="max-w-[70ch] text-ink-soft">MedCheck warns you as each medication's supply gets low.</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          {[["first", "First reminder"], ["second", "Second reminder"], ["urgent", "Urgent"]].map(([k, label]) => (
            <label key={k} className="flex flex-col gap-1.5">
              <span className="font-bold">{label}</span>
              <span className="flex items-center gap-2"><input className="field w-20 text-center" inputMode="numeric" value={s.thresholds[k]} onChange={(e) => setT(k, e.target.value)} /> days left</span>
            </label>
          ))}
        </div>
        <Toggle label="Text me when Rosa misses a dose by more than 1 hour" checked={s.alert_missed} onChange={(v) => set({ alert_missed: v })} />
        <Toggle label="Text me when a prescription has no refills left" checked={s.alert_no_refills} onChange={(v) => set({ alert_no_refills: v })} />
        <Toggle label="Text me when MedCheck catches a wrong bottle" checked={s.alert_wrong_bottle} onChange={(v) => set({ alert_wrong_bottle: v })} />
      </Card>

      <Card as="section" aria-labelledby="rem-h" className="flex flex-col gap-4">
        <div>
          <h2 id="rem-h" className="text-xl font-bold">{data.patient.name}'s reminders</h2>
          <p className="max-w-[70ch] text-ink-soft">How MedCheck speaks to {data.patient.name} through the wearable.</p>
        </div>
        <label className="flex max-w-xs flex-col gap-1.5">
          <span className="font-bold">Remind again if a dose is missed</span>
          <select className="field" value={s.remind_again} onChange={(e) => set({ remind_again: e.target.value })}>
            <option value="30">After 30 minutes</option>
            <option value="60">After 1 hour</option>
            <option value="never">Don't remind again</option>
          </select>
        </label>
        <label className="flex max-w-xs flex-col gap-1.5">
          <span className="font-bold">Voice language</span>
          <select className="field" value={s.voice_language} onChange={(e) => set({ voice_language: e.target.value })}>
            <option>English</option><option>Spanish</option><option>Portuguese</option>
          </select>
        </label>
      </Card>

      {(dirty || saved) && (
        <div className="sticky bottom-24 z-30 flex items-center justify-end gap-3 rounded-full bg-white/90 p-2 shadow-dialog backdrop-blur xl:col-span-2">
          {saved && !dirty && <span role="status" className="mr-auto pl-4 font-bold text-ok">Settings saved</span>}
          {dirty && <Button variant="secondary" onClick={() => setS(data.settings)}>Undo changes</Button>}
          <Button onClick={() => save()} busy={busy === "save"} disabled={!dirty}>Save settings</Button>
        </div>
      )}

      <Card as="section" aria-labelledby="priv-h" className="flex flex-col gap-4">
        <div>
          <h2 id="priv-h" className="text-xl font-bold">Privacy</h2>
          <p className="max-w-[70ch] text-ink-soft">Everything is processed on the hub in {data.patient.name}'s home. Camera images are never saved.</p>
        </div>
        <div className="rounded-2xl bg-mist px-5 py-4">
          <strong>What MedCheck stores</strong>
          <p>Medication names and label details, when each dose was taken, pill counts, and the texts it sent.</p>
        </div>
        <div className="flex flex-wrap gap-2.5">
          <Button variant="secondary" busy={busy === "cam"} onClick={async () => { setBusy("cam"); try { await run(() => api.saveSettings({ ...data.settings, camera_paused: !data.settings.camera_paused })); } finally { setBusy(null); } }}>
            {data.settings.camera_paused ? "Turn the camera back on" : "Pause the camera"}
          </Button>
          <Button variant="secondary" onClick={exportData}>Download {data.patient.name}'s data</Button>
          <Button variant="danger" onClick={() => setConfirmDelete(true)}>Delete all data</Button>
        </div>
        {data.settings.camera_paused && <Notice tone="low" title="The camera is paused">MedCheck won't check bottles or confirm doses until you turn it back on.</Notice>}
      </Card>

      <Dialog open={confirmDelete} onClose={() => setConfirmDelete(false)} label="Delete all data" className="max-w-lg">
        <div className="flex flex-col gap-4">
          <h2 className="text-2xl font-bold">Delete all of {data.patient.name}'s data?</h2>
          <p>This removes every medication, dose and text from the hub. It can't be undone. Your settings and caregivers are kept.</p>
          <div className="flex justify-end gap-3">
            <Button variant="secondary" onClick={() => setConfirmDelete(false)}>Keep data</Button>
            <Button variant="danger" busy={busy === "del"} onClick={async () => { setBusy("del"); try { await run(api.deleteAll); setConfirmDelete(false); } finally { setBusy(null); } }}>Delete all data</Button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}
