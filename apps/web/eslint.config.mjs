import eslint from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

const typedFiles = ["**/*.{ts,tsx}"];
const strictTyped = tseslint.configs.strictTypeChecked.map((config) => ({
  ...config,
  files: typedFiles,
}));
const stylisticTyped = tseslint.configs.stylisticTypeChecked.map((config) => ({
  ...config,
  files: typedFiles,
}));

export default tseslint.config(
  { ignores: ["dist/**", "playwright-report/**", "test-results/**"] },
  eslint.configs.recommended,
  ...strictTyped,
  ...stylisticTyped,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["error", { allowConstantExport: true }],
      "@typescript-eslint/consistent-type-imports": "error",
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/no-misused-promises": "error",
      "@typescript-eslint/no-unnecessary-condition": "error",
      "@typescript-eslint/prefer-readonly": "error",
    },
  },
);
