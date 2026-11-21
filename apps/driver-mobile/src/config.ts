// Runtime configuration. EXPO_PUBLIC_* values are inlined at build time (never put secrets here:
// the app is a public OAuth client and holds no client secret).
//
// Defaults target the local development issuer (DECISIONS D-006) from an Android emulator, where
// the host machine is 10.0.2.2. With Cognito, AUTH_* point at the user pool's hosted domain
// (/oauth2/authorize, /oauth2/token) and CLIENT_ID is the driver-mobile app client.
const env = process.env;

export const API_BASE_URL = env.EXPO_PUBLIC_API_BASE_URL ?? 'http://10.0.2.2:8000';

export const AUTH = {
  clientId: env.EXPO_PUBLIC_AUTH_CLIENT_ID ?? 'local-driver-mobile',
  authorizationEndpoint: env.EXPO_PUBLIC_AUTH_AUTHORIZE_URL ?? `${API_BASE_URL}/dev-auth/authorize`,
  tokenEndpoint: env.EXPO_PUBLIC_AUTH_TOKEN_URL ?? `${API_BASE_URL}/dev-auth/token`,
  // Must match app.json "scheme" and the redirect URIs registered with the issuer.
  redirectScheme: 'corridor-driver',
  redirectPath: 'auth/callback',
  scopes: ['openid', 'phone'],
} as const;
