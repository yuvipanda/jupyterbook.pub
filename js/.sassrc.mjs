import sass from "sass";
const config = {
    silenceDeprecations: ["import", "mixed-decls", "color-functions", "global-builtin"],
    importers: [new sass.NodePackageImporter()],
};

export default config;
