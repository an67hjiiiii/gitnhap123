import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";

const ChatRoute = lazy(() => import("./ChatRoute"));
const StudioRoot = lazy(() => import("./studio/StudioRoot"));

const root = document.getElementById("root");

if (!root) {
  throw new Error("Frontend root element was not found");
}

// /chat: giao diện trò chuyện gốc. Các đường dẫn khác: giao diện Studio (/, /login, /register, /studio).
createRoot(root).render(
  <StrictMode>
    <BrowserRouter>
      <Suspense fallback={<div role="status" style={{ padding: 24 }}>Đang tải…</div>}>
        <Routes>
          <Route path="/chat/*" element={<ChatRoute />} />
          <Route path="*" element={<StudioRoot />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  </StrictMode>,
);
