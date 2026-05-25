/*
\chapter*{Seznam zkratek}
\addcontentsline{toc}{chapter}{Seznam zkratek}

\begin{acronym}[FWHM] % [FWHM] sets the alignment width based on this string
    \acro{FITS}{Flexible Image Transport System}
    \acro{FWHM}{Full Width at Half Maximum}
    \acro{HFR}{Half Flux Radius}
    \acro{MAD}{Median Absolute Deviation}
    \acro{HDU}{Header/Data Unit}
    \acro{UI}{User Interface}
    \acro{HFD}{Half Flux Diameter}
    \acro{PSF}{Point Spread Function}
    \acro{SEP}{Source Extraction and Photometry}
    \acro{RMS}{Root Mean Square}
    \acro{SNR}{Signal-To-Noise Ratio}
    \acro{IPC}{Inter proces communication}
    \acro{DOM}{Document Object Model}
    \acro{CPU}{Central Processing Unit}
    \acro{WebGL}{Web Graphics Library}
\end{acronym}
*/

const fs = require("node:fs");

function sortAcronymsContent(content: string): string {
    // locate the acronym environment block
    const blockRegex = /\\begin\{acronym\}[\s\S]*?\\end\{acronym\}/m;
    const blockMatch = content.match(blockRegex);
    if (!blockMatch) return content;
    const block = blockMatch[0];

    const lines = block.split(/\r?\n/);
    const acroIndexes = lines.map((l, i) => (l.includes("\\acro{") ? i : -1)).filter(i => i >= 0);
    if (acroIndexes.length === 0) return content;

    const first = acroIndexes[0];
    const last = acroIndexes[acroIndexes.length - 1];
    const acroLines = lines.slice(first, last + 1);

    const keyRe = /\\acro\{([^}]+)\}/;
    const sortedAcros = acroLines.slice().sort((a, b) => {
        const ka = (a.match(keyRe)?.[1] ?? "").toLowerCase();
        const kb = (b.match(keyRe)?.[1] ?? "").toLowerCase();
        return ka.localeCompare(kb, undefined, { sensitivity: "base" });
    });

    const newBlock = [...lines.slice(0, first), ...sortedAcros, ...lines.slice(last + 1)].join("\n");
    return content.replace(block, newBlock);
}

const inputPath = "acronyms.tex";
const outputPath = "acronyms.sorted.tex";
try {
    const acronyms = fs.readFileSync(inputPath, "utf-8");
    const sorted = sortAcronymsContent(acronyms);
    fs.writeFileSync(outputPath, sorted, "utf-8");
    console.log(`Wrote sorted acronyms to ${outputPath}`);
} catch (err: any) {
    console.error("Error sorting acronyms:", err?.message ?? err);
}
