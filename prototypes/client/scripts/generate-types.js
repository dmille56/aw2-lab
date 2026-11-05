import fs from "node:fs/promises";
import openapiTS, { astToString } from "openapi-typescript";
import Ajv from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import standaloneCode from "ajv/dist/standalone/index.js";

const source = new URL("../schemas/api-v1.json", import.meta.url);
const schema = JSON.parse(await fs.readFile(source, "utf8"));
const types = astToString(await openapiTS(schema));
const ajv = new Ajv({
  strict: false,
  code: { source: true, esm: true },
  formats: { uuid: true, "date-time": true },
});
addFormats(ajv, { formats: ["uuid"] });
// Date-time semantics remain checked on the Python boundary. UUID formats use
// an inline regex; no dynamic code generation is allowed in the webview.
ajv.addFormat("date-time", true);
const validate = ajv.compile({
  ...schema,
  $ref: "#/components/schemas/StateResponse",
});
const outputs = {
  "api.ts": types,
  "validate-state.js": standaloneCode(ajv, validate),
  "validate-state.d.ts":
    "export default function validate(value: unknown): boolean;\n",
};
const identity = ajv.compile({
  ...schema,
  $ref: "#/components/schemas/MatchIdentityResponse",
});
outputs["validate-identity.js"] = standaloneCode(ajv, identity);
outputs["validate-identity.d.ts"] =
  "export default function validate(value: unknown): boolean;\n";
const capabilities = ajv.compile({
  ...schema,
  $ref: "#/components/schemas/CapabilitiesResponse",
});
outputs["validate-capabilities.js"] = standaloneCode(ajv, capabilities);
outputs["validate-capabilities.d.ts"] =
  "export default function validate(value: unknown): boolean;\n";
for (const name of ["CommandReceipt", "CommandResult"]) {
  const validator = ajv.compile({
    ...schema,
    $ref: `#/components/schemas/${name}`,
  });
  outputs[`validate-${name === "CommandReceipt" ? "receipt" : "result"}.js`] =
    standaloneCode(ajv, validator);
  outputs[`validate-${name === "CommandReceipt" ? "receipt" : "result"}.d.ts`] =
    "export default function validate(value: unknown): boolean;\n";
}
const check = process.argv.includes("--check");
for (const [name, text] of Object.entries(outputs)) {
  const destination = new URL(`../web/generated/${name}`, import.meta.url);
  if (check) {
    if ((await fs.readFile(destination, "utf8")) !== text)
      throw new Error(`Generated ${name} is stale; run npm run generate`);
  } else {
    await fs.mkdir(new URL("../web/generated/", import.meta.url), {
      recursive: true,
    });
    await fs.writeFile(destination, text);
  }
}
