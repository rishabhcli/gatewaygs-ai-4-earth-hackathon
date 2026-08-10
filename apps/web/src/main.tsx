import "@fontsource-variable/ibm-plex-sans";
import "@fontsource-variable/source-serif-4";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./styles.css";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("ROOT_ELEMENT_MISSING");
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
