export default function SourcePicker({ name = "source", glassesNote = "Coming after the MVP. Rosa will just look at the bottle.", stacked = false }) {
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-2 font-bold">Scan with</legend>
      <div className={`grid gap-2.5 ${stacked ? "" : "sm:grid-cols-2"}`}>
        <label className="flex cursor-pointer items-start gap-3 rounded-[22px] bg-mist px-4 py-3.5 shadow-[inset_0_0_0_2px_#9CC3EC]">
          <input type="radio" name={name} defaultChecked className="mt-1 h-5 w-5 accent-navy" />
          <span><strong>Computer camera</strong><br /><span className="text-[15px] text-ink-soft">For this demo. Hold the bottle up to the webcam.</span></span>
        </label>
        <label className="flex items-start gap-3 rounded-[22px] border border-dashed border-[#C3D1E3] bg-white px-4 py-3.5 text-ink-muted">
          <input type="radio" name={name} disabled className="mt-1 h-5 w-5" />
          <span><strong>Meta AI glasses</strong><br /><span className="text-[15px]">{glassesNote}</span></span>
        </label>
      </div>
    </fieldset>
  );
}
