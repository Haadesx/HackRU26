import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Button from "../../components/Button";
import { api } from "../../api/client";
import ScanSteps from "./ScanSteps";
import SourcePicker from "./SourcePicker";
import CameraView from "./CameraView";
import FoundSoFar from "./FoundSoFar";
import { rememberVerification } from "../../lib/verificationCache";

export default function ScanPage() {
  const navigate = useNavigate();
  const [scan, setScan] = useState(null);
  const [photos, setPhotos] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const file = useRef(null);

  useEffect(() => () => photos.forEach((p) => URL.revokeObjectURL(p)), [photos]);

  const send = async (blob) => {
    setBusy(true); setError(null);
    try {
      const next = scan ? await api.addPhoto(scan.id, blob) : await api.startScan(blob);
      rememberVerification(next);
      setScan(next);
      setPhotos((p) => [...p, URL.createObjectURL(blob)]);
    } catch (e) {
      setError(`Couldn't read that photo. ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  const manual = async () => {
    const s = await api.startManual();
    navigate(`/scan/${s.id}/verify`);
  };

  return (
    <div className="flex flex-col gap-7">
      <header className="flex flex-wrap items-end justify-between gap-5">
        <div>
          <h1 className="text-[38px] font-bold leading-tight">Scan a pill bottle</h1>
          <p className="max-w-[62ch] text-ink-soft">Hold the bottle up to your computer's camera with the label facing it. MedCheck reads it and fills in the medication details for you to check.</p>
        </div>
        <ScanSteps current={0} />
      </header>

      <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)] xl:grid-cols-[minmax(0,1.8fr)_minmax(0,1fr)]">
        <section aria-label="Camera" className="flex flex-col gap-4">
          <SourcePicker />
          <CameraView onCapture={send} busy={busy} />
          {error && <p role="alert" className="rounded-2xl bg-urgent-tint px-4 py-3 font-bold text-urgent">{error}</p>}
          <div className="flex flex-col gap-2">
            <strong>Photos of this bottle</strong>
            <p className="text-[15px] text-ink-soft">Labels wrap around the bottle. Turn it slowly in front of the camera and take another photo until every detail is found.</p>
            <ul className="flex flex-wrap gap-2.5">
              {photos.map((src, i) => (
                <li key={src}><img src={src} alt={`Photo ${i + 1} of the label`} className="h-[90px] w-[120px] rounded-xl border-[3px] border-ok-pill object-cover" /></li>
              ))}
              <li aria-hidden="true" className="flex h-[90px] w-[120px] items-center justify-center rounded-xl border-2 border-dashed border-[#C3D1E3] text-sm text-ink-soft">
                {busy ? "Reading…" : "Next photo"}
              </li>
            </ul>
          </div>
        </section>

        <aside className="flex flex-col gap-5 xl:sticky xl:top-8">
          <FoundSoFar scan={scan} />
          <section aria-labelledby="nocam-h" className="flex flex-col items-start gap-2.5">
            <h2 id="nocam-h" className="text-lg font-bold">No camera?</h2>
            <input ref={file} type="file" accept="image/*" className="sr-only" onChange={(e) => e.target.files?.[0] && send(e.target.files[0])} />
            <Button variant="secondary" onClick={() => file.current?.click()}>Upload a photo of the label</Button>
            <button type="button" className="link" onClick={manual}>Enter the details by hand</button>
          </section>
          <p className="border-t border-line pt-4 text-[15px] text-ink-soft">Photos go only to the MedCheck hub to be read, and are deleted once you add the medication.</p>
        </aside>
      </div>
    </div>
  );
}
