// ESLint flat config (Expo SDK 53+), per https://docs.expo.dev/guides/using-eslint/
const { defineConfig, globalIgnores } = require('eslint/config');
const expoConfig = require('eslint-config-expo/flat');

module.exports = defineConfig([globalIgnores(['dist/*', '.expo/*']), expoConfig]);
