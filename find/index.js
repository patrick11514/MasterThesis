const fs = require("node:fs");
const path = require("node:path")

const files = fs.readdirSync(path.join(__dirname, "..", "TRAINING_FILES"));



const jsons = files.filter(f => f.endsWith(".json"));
const fits = files.filter(f => f.endsWith(".fit") || f.endsWith(".fits"));

const missing = jsons.filter(json => !fits.some(fit => fit.startsWith(json.split(".")[0])));

console.log(missing);