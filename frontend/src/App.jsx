import { Route, Routes, Navigate } from "react-router-dom";
import AppShell from "./layout/AppShell";
import HomePage from "./pages/Home/HomePage";
import ScanPage from "./pages/Scan/ScanPage";
import VerifyPage from "./pages/Scan/VerifyPage";
import AddedPage from "./pages/Scan/AddedPage";
import HistoryPage from "./pages/History/HistoryPage";
import SettingsPage from "./pages/Settings/SettingsPage";

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/scan" element={<ScanPage />} />
        <Route path="/scan/:scanId/verify" element={<VerifyPage />} />
        <Route path="/scan/added/:medId" element={<AddedPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}
