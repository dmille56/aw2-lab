import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import Ajv from "ajv";
import addFormats from "ajv-formats";
const read = (path) =>
  JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8"));
// Tauri emits Rust regex escapes that require non-Unicode JavaScript regex mode.
const ajv = new Ajv({ strict: false, allErrors: true, unicodeRegExp: false });
addFormats(ajv);
for (const [name, maximum] of [
  ["uint8", 255],
  ["uint32", 4294967295],
]) {
  ajv.addFormat(name, {
    type: "number",
    validate: (value) =>
      Number.isInteger(value) && value >= 0 && value <= maximum,
  });
}
const validate = ajv.compile(read("../schemas/tauri-config.schema.json"));
if (!validate(read("../tauri.conf.json"))) {
  throw new Error(
    `Invalid Tauri configuration: ${ajv.errorsText(validate.errors)}`,
  );
}
const pkg = read("../package.json");
const lock = read("../package-lock.json");
assert.equal(pkg.private, true);
assert.equal(pkg.type, "module");
assert.equal(lock.lockfileVersion, 3);
assert.deepEqual(
  lock.packages[""].devDependencies,
  pkg.devDependencies,
  "package-lock.json dependencies must match package.json",
);
console.log("Tauri schema and npm lock consistency passed");
