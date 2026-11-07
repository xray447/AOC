import "@ant-design/v5-patch-for-react-19";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { StandOverlay } from "./pages/StandOverlay";
import "./styles.css";

// docs/12 §6.3.2：Tauri 置顶浮窗用同一个 bundle，`?overlay=1` 时只渲染一张小板。
const overlay = new URLSearchParams(window.location.search).has("overlay");
if (overlay) document.documentElement.classList.add("overlay-mode");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      {overlay ? <StandOverlay /> : <App />}
    </BrowserRouter>
  </StrictMode>,
);
