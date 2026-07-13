// @liviq/ui — ESLint flat config (React 라이브러리, TS)
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['node_modules', 'dist'] },
  ...tseslint.configs.recommended,
);
