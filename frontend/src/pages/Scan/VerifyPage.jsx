import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import Button from "../../components/Button";
import TextField from "../../components/TextField";
import { api } from "../../api/client";
import { useAppState } from "../../state/AppState";
import { FIELDS, REQUIRED } from "./fields";
import ScanSteps from "./ScanSteps";
import ScanTimeline from "./ScanTimeline";
import PreviewDialog from "./PreviewDialog";
import ScanVerification from "./ScanVerification";
import { cachedVerification } from "../../lib/verificationCache";

export default function VerifyPage() {
  const { scanId } = useParams();
  const navigate = useNavigate();
  const { refresh } = useAppState();
  const [scan, setScan] = useState(null);
  const [values, setValues] = useState({});
  const [loadError, setLoadError] = useState(null);
  const [preview, setPreview] = useState(false);
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState(null);

  useEffect(() => {
    api.getScan(scanId)
      .then((s) => {
        const verification = s.verification ?? cachedVerification(s.id);
        setScan(verification ? { ...s, verification } : s);
        setValues(Object.fromEntries(FIELDS.map((f) => [f.key, s.fields[f.key].value])));
      })
      .catch((e) => setLoadError(e.message));
  }, [scanId]);

  // What the caregiver typed: missing → "added", unsure → "corrected".
  const changed = useMemo(() => {
    if (!scan) return {};
    const out = {};
    for (const f of FIELDS) {
      const orig = scan.fields[f.key];
      if (values[f.key] !== orig.value && String(values[f.key]).trim()) out[f.key] = orig.state === "missing" ? "added" : "corrected";
    }
    return out;
  }, [scan, values]);

  if (loadError) return <p role="alert" className="rounded-2xl bg-urgent-tint p-5 font-bold text-urgent">{loadError}</p>;
  if (!scan) return <p role="status" className="text-ink-soft">Loading the scan…</p>;

  const fromRosa = scan.history?.length > 1;
  const name = values.name || "this medication";
  const stillMissing = REQUIRED.filter((k) => !String(values[k] ?? "").trim());
  const flagged = FIELDS.filter((f) => scan.fields[f.key].state !== "filled").length;

  const stateOf = (f) => {
    const orig = scan.fields[f.key].state;
    if (changed[f.key]) return "filled";
    return orig;
  };

  const add = async () => {
    setAdding(true); setAddError(null);
    try {
      const { medication } = await api.completeScan(scan.id, values);
      await refresh();
      navigate(`/scan/added/${medication.id}`, { replace: true });
    } catch (e) {
      setAddError(e.message);
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="flex flex-col gap-7">
      <header className="flex flex-wrap items-end justify-between gap-5">
        <div className="flex flex-col gap-1.5">
          <h1 className="text-[38px] font-bold leading-tight">
            {scan.manual ? "Add a medication by hand" : fromRosa ? `Help Rosa finish adding ${name}` : `Check ${name}`}
          </h1>
          <p className="max-w-[64ch] text-ink-soft">
            {scan.manual
              ? "Fill in the details from the bottle's label."
              : fromRosa
                ? `MedCheck read most of the label, but ${flagged} ${flagged === 1 ? "detail needs" : "details need"} you. Rosa couldn't add them by voice. MedCheck won't remind her about this medication until it's complete.`
                : "Check what MedCheck read from the label and fill in anything missing."}
          </p>
        </div>
        <ScanSteps current={1} />
      </header>

      {fromRosa && <ScanTimeline history={scan.history} />}

      {scan.verification && <ScanVerification verification={scan.verification} />}

      <form
        className="card grid gap-5 p-6 sm:p-7"
        onSubmit={(e) => { e.preventDefault(); if (!stillMissing.length) setPreview(true); }}
        noValidate
      >
        <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {FIELDS.map((f) => {
            const st = stateOf(f);
            const note = st === "missing" ? `Missing. ${f.why || "Check the label."}` : st === "unsure" ? "MedCheck couldn't read this clearly. Check it against the bottle." : null;
            return (
              <TextField key={f.key} id={`f-${f.key}`} label={f.label + (f.required ? "" : " (optional)")} state={st} note={note}
                placeholder={f.placeholder} inputMode={f.inputMode} value={values[f.key] ?? ""}
                onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} className={f.wide ? "sm:col-span-2 xl:col-span-3" : ""} />
            );
          })}
        </div>
        <div className="rounded-2xl bg-mist px-5 py-4">
          <strong>What MedCheck will do</strong>
          <p>Remind Rosa at each dose time, and text you when fewer than 7 days of tablets are left.</p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-3">
          {stillMissing.length > 0 && <span className="mr-auto text-[15px] font-bold text-urgent">Fill in {stillMissing.length} more required {stillMissing.length === 1 ? "detail" : "details"} to continue.</span>}
          <Button variant="secondary" onClick={async () => { await api.discardScan(scan.id); await refresh(); navigate("/"); }}>Discard</Button>
          <Button type="submit" size="lg" disabled={stillMissing.length > 0}>Preview</Button>
        </div>
      </form>

      <PreviewDialog open={preview} values={values} changed={changed} adding={adding} error={addError}
        onEdit={() => { setPreview(false); setAddError(null); }} onAdd={add} />
    </div>
  );
}
