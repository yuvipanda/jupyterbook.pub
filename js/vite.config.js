import react from "@vitejs/plugin-react";

export default {
    plugins: [react()],
    base: "./",
    build: {
        target: "esnext",
        lib: {
            entry: "src/index.tsx",
            cssFileName: "index",
            formats: ["es"],
            fileName: "index",
        },
        outDir: "../src/jupyterbook_pub/generated_static/",
    },
    define: {
        "process.env.NODE_ENV": `"production"`,
    },
    // Optional: Silence Sass deprecation warnings. See note below.
    css: {
        preprocessorOptions: {
            scss: {
                silenceDeprecations: [
                    "import",
                    "mixed-decls",
                    "color-functions",
                    "global-builtin",
                ],
            },
        },
    },
};
