import { useAppState } from "../state/AppState";

export default function HubStatus() {
  const { connected, data } = useAppState();
  const ok = connected && data;
  return (
    <span role="status" className={`inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-[15px] font-bold ${ok ? "bg-ok-fill text-ok" : "bg-urgent-fill text-urgent"}`}>
      <span aria-hidden="true" className={`h-2.5 w-2.5 rounded-full ${ok ? "bg-[#5FB07C]" : "bg-[#E0786B]"}`} />
      {ok ? `Connected to ${data.patient.name}'s hub` : "Can't reach the hub. Retrying."}
    </span>
  );
}
