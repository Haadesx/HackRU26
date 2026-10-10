import { useCallback, useEffect, useRef, useState } from "react";
import Button from "../../components/Button";
import Notice from "../../components/Notice";

/**
 * Webcam source for the MVP. Later, the Meta glasses become a second source that
 * produces the same photo blobs, and nothing downstream changes.
 */
export default function CameraView({ onCapture, busy }) {
  const video = useRef(null);
  const stream = useRef(null);
  const [status, setStatus] = useState("starting"); // starting | live | blocked | unsupported
  const [devices, setDevices] = useState([]);
  const [deviceId, setDeviceId] = useState("");

  const stop = () => stream.current?.getTracks().forEach((t) => t.stop());

  const start = useCallback(async (id) => {
    stop();
    if (!navigator.mediaDevices?.getUserMedia) return setStatus("unsupported");
    setStatus("starting");
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({
        video: id ? { deviceId: { exact: id } } : { width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: false,
      });
      if (video.current) video.current.srcObject = stream.current;
      setStatus("live");
      const all = await navigator.mediaDevices.enumerateDevices();
      setDevices(all.filter((d) => d.kind === "videoinput"));
    } catch {
      setStatus("blocked");
    }
  }, []);

  useEffect(() => {
    start();
    return stop;
  }, [start]);

  const capture = () => {
    const v = video.current;
    if (!v?.videoWidth) return;
    const c = document.createElement("canvas");
    c.width = v.videoWidth;
    c.height = v.videoHeight;
    c.getContext("2d").drawImage(v, 0, 0);
    c.toBlob((blob) => blob && onCapture(blob), "image/jpeg", 0.92);
  };

  if (status === "blocked" || status === "unsupported") {
    return (
      <Notice tone="low" title={status === "blocked" ? "Camera is blocked" : "This browser can't use the camera"}
        actions={status === "blocked" && <Button variant="secondary" onClick={() => start(deviceId)}>Try again</Button>}>
        {status === "blocked"
          ? "Allow camera access in your browser's address bar, then try again. Or upload a photo instead."
          : "Upload a photo of the label instead, or enter the details by hand."}
      </Notice>
    );
  }

  return (
    <div className="flex flex-col gap-3.5">
      <div className="relative aspect-[4/3] overflow-hidden rounded-[18px] bg-[#2B3A4D]">
        <video ref={video} autoPlay playsInline muted className="h-full w-full object-cover" aria-label="Live webcam view" />
        <div aria-hidden="true" className="pointer-events-none absolute inset-x-[16%] inset-y-[22%] rounded-2xl border-[3px] border-white shadow-[0_0_0_2000px_rgba(21,34,56,0.4)]" />
        <span className="absolute left-1/2 top-[8%] -translate-x-1/2 whitespace-nowrap rounded-full bg-white px-4 py-1.5 text-[15px] font-bold">
          Hold the label inside the frame, about a hand's length away
        </span>
        <span className="absolute bottom-[7%] left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full bg-ok-fill px-4 py-1.5 text-[15px] font-bold text-ok">
          {status === "live" ? "Hold still, then take the photo." : "Starting the camera…"}
        </span>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          {devices.length > 1 && (
            <label className="flex items-center gap-2.5">
              <span className="font-bold">Webcam</span>
              <select className="field w-auto" value={deviceId} onChange={(e) => { setDeviceId(e.target.value); start(e.target.value); }}>
                {devices.map((d, i) => <option key={d.deviceId} value={d.deviceId}>{d.label || `Camera ${i + 1}`}</option>)}
              </select>
            </label>
          )}
          <span className="text-[15px] text-ink-soft">Tip: face a window or lamp so the label isn't in shadow.</span>
        </div>
        <Button size="lg" onClick={capture} busy={busy} disabled={status !== "live"}>Take photo</Button>
      </div>
    </div>
  );
}
