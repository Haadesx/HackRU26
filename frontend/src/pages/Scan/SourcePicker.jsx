export default function SourcePicker() {
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-2 font-bold">Scan with</legend>
      <div className="grid gap-2.5 sm:grid-cols-2">
        <label className="flex cursor-pointer items-start gap-3 rounded-[22px] bg-mist px-4 py-3.5 shadow-[inset_0_0_0_2px_#9CC3EC]">
          <input type="radio" name="source" defaultChecked className="mt-1 h-5 w-5 accent-navy" />
          <span><strong>Computer camera</strong><br /><span className="text-[15px] text-ink-soft">For this demo. Hold the bottle up to the webcam.</span></span>
        </label>
        <label className="flex items-start gap-3 rounded-[22px] border border-dashed border-[#C3D1E3] bg-white px-4 py-3.5 text-ink-muted">
          <input type="radio" name="source" disabled className="mt-1 h-5 w-5" />
          <span><strong>Meta AI glasses</strong><br /><span className="text-[15px]">Coming after the MVP. Rosa will just look at the bottle.</span></span>
        </label>
      </div>
    </fieldset>
  );
}
