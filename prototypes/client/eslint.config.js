import js from "@eslint/js";
import globals from "globals";

export default [
  {
    ignores: [
      "node_modules/**",
      "target/**",
      "gen/**",
      "coverage/**",
      "test-results/**",
      "playwright-report/**",
    ],
  },
  js.configs.recommended,
  {
    languageOptions: { globals: globals.browser },
    rules: { eqeqeq: "error", "no-var": "error", "prefer-const": "error" },
  },
  {
    files: ["*.js", "scripts/**/*.js", "tests/**/*.js"],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
  },
];
