import { createRoot } from "react-dom/client";
import { App } from "./App";
import { initializeTheme } from "./appearance";
import "./style.css";

initializeTheme();

const root = document.getElementById("root");
if (!root) throw new Error("Client root is missing");
createRoot(root).render(<App />);
