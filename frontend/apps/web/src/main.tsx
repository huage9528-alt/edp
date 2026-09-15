import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AppMain } from "./app/main";
import "./styles/tokens.css";
import "./styles/app.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppMain />
  </StrictMode>,
);
