import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import {
  applyStandaloneClass,
  registerServiceWorker,
  watchAppHeight,
  watchStandalone,
} from "./pwa";
import "./styles.css";

applyStandaloneClass();
watchStandalone();
watchAppHeight();
registerServiceWorker();

const root = document.getElementById("root");
if (root) {
  ReactDOM.createRoot(root).render(
    <React.StrictMode>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </React.StrictMode>,
  );
}
