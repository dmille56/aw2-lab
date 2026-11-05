import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./style.css";

const root = document.getElementById("root");
if (!root) throw new Error("Client root is missing");
createRoot(root).render(<App />);
