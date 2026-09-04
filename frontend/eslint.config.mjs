import nextPlugin from "@next/eslint-plugin-next";
import tsParser from "@typescript-eslint/parser";

export default [
  {
    files: ["**/*.{js,jsx,mjs,ts,tsx}"],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: "latest",
        sourceType: "module",
        ecmaFeatures: { jsx: true }
      }
    },
    plugins: {
      "@next/next": nextPlugin
    },
    rules: {
      ...nextPlugin.configs.recommended.rules,
      ...nextPlugin.configs["core-web-vitals"].rules,
      "no-constant-binary-expression": "error",
      "no-dupe-keys": "error",
      "no-unreachable": "error"
    }
  },
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      "next-env.d.ts"
    ]
  }
];
