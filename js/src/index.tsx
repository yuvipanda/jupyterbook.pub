import { createRoot } from "react-dom/client";
import { StrictMode } from "react";
import { App } from "./App";

import "./index.scss";

export default function renderApp({
    title,
    heading,
    subheading,
    baseUrl,
}: {
    title: string;
    heading: string;
    subheading: string;
    baseUrl: string;
}) {
    let container = document.getElementById("root")!;
    let root = createRoot(container);
    root.render(
        <StrictMode>
            <App
                title={title}
                heading={heading}
                subheading={subheading}
                baseUrl={baseUrl}
            />
        </StrictMode>,
    );
}
