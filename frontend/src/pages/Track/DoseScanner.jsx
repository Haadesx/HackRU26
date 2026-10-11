import { useRef, useState } from "react";
import Button from "../../components/Button";
import Notice from "../../components/Notice";
import { api, usingMock } from "../../api/client";
import { useAppState } from "../../state/AppState";
import { doseDueNow } from "../../lib/doses";
import { fmtSlot, fmtTime } from "../../lib/format";
import SourcePicker from "../Scan/SourcePicker";
import CameraView from "../Scan/CameraView";

/**
 * Scan a bottle at dose time: the hub checks it's the right medicine, then a person
 * confirms it was taken. A scan alone never records a dose.
 * Today the source is the webcam; the Meta glasses become a second source later.
 */
export default function DoseScanner() {
  const { data, run, refresh } = useAppState();
  const [result, setResult] = useState(null);
  const [done, setDone] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [demoMed, setDemoMed] = useState("");
  const file = useRef(null);
  const due = doseDueNow(data);

  const check = async (blob) => {
    setBusy("scan"); setError(null); setDone(null);
    try {
      const r = await api.matchDose(blob, demoMed ? Number(demoMed) : undefined);
      setResult(r);
      if (r.status === "wrong_bottle") await refresh(); // the catch shows under Mistakes caught
    } catch (e) {
      setError(`Couldn't check that bottle. ${e.message}`);
    } finally {
      setBusy(null);
    }
  };

  const confirm = async () => {
    setBusy("confirm"); setError(null);
    try {
      await run(() => api.logDose(result.medication_id, result.slot, "scan"));
      setDone({ name: result.name, at: data.now });
      setResult(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const reset = () => { setResult(null); setDone(null); setError(null); };

  return (
    <section aria-labelledby="scanner-h" className="card flex flex-col gap-4 p-5 shadow-[inset_0_0_0_1px_#9CC3EC]">
      <div>
        <h2 id="scanner-h" className="text-xl font-bold">Dose scanner</h2>
        <p className="text-[15px] text-ink-soft">
          {due
            ? `${due.state === "upcoming" ? "Next" : "Due now"}: ${due.med.name} at ${fmtSlot(due.slot)}.`
            : "Every dose today is done."}{" "}
          Hold the bottle up to the camera when it's time.
        </p>
      </div>

      <SourcePicker name="dose-source" glassesNote="Coming after the MVP. Will log doses automatically." stacked />

      {usingMock && !result && !done && (
        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-bold text-ink-soft">Demo: which bottle is in view?</span>
          <select className="field" value={demoMed} onChange={(e) => setDemoMed(e.target.value)}>
            <option value="">The one that's due{due ? ` (${due.med.name})` : ""}</option>
            {data.medications.map((m) => <option key={m.id} value={m.id}>{m.name} {m.strength}</option>)}
          </select>
        </label>
      )}

      {result?.status === "match" && (
        <Notice tone="ok" title={`That's ${result.name} ${result.strength}`}
          actions={<><Button variant="secondary" onClick={reset}>Not now</Button><Button busy={busy === "confirm"} onClick={confirm}>Rosa took it</Button></>}>
          Due at {fmtSlot(result.slot)}{result.late ? ", so it's late" : ""}. Press <strong>Rosa took it</strong> only after she's taken it.
        </Notice>
      )}
      {result?.status === "wrong_bottle" && (
        <Notice tone="urgent" title="Wrong bottle" actions={<Button variant="secondary" onClick={reset}>Scan again</Button>}>
          That's {result.name}. {result.expected.name} is due now, at {fmtSlot(result.expected.slot)}. Put this one back.
        </Notice>
      )}
      {result?.status === "already_taken" && (
        <Notice tone="low" title="Already taken" actions={<Button variant="secondary" onClick={reset}>Scan again</Button>}>
          {result.name} was taken{result.taken_at ? ` at ${fmtTime(result.taken_at)}` : ""}. Taking it again would be a double dose.
        </Notice>
      )}
      {result?.status === "not_scheduled" && (
        <Notice tone="info" title="Nothing due" actions={<Button variant="secondary" onClick={reset}>Scan again</Button>}>{result.message}</Notice>
      )}
      {done && (
        <Notice tone="ok" title="Marked as taken" actions={<Button variant="secondary" onClick={reset}>Scan another</Button>}>
          {done.name} at {fmtTime(done.at)}. One pill came off the bottle.
        </Notice>
      )}
      {error && <p role="alert" className="rounded-2xl bg-urgent-tint px-4 py-3 font-bold text-urgent">{error}</p>}

      {!result && !done && (
        <>
          <CameraView onCapture={check} busy={busy === "scan"} hint="Hold the bottle's label in the frame" captureLabel="Scan this dose" compact />
          <input ref={file} type="file" accept="image/*" className="sr-only" onChange={(e) => e.target.files?.[0] && check(e.target.files[0])} />
          <button type="button" className="link self-start" onClick={() => file.current?.click()}>No camera? Upload a photo of the bottle</button>
        </>
      )}
    </section>
  );
}
