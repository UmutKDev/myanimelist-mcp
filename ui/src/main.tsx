import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./theme/fonts.css";
import "./theme/global.css";
import "./theme/components.css";
import "./theme/views.css";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
