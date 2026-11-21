# Driver app — builds and credentials

The app uses native modules (background location, foreground service, SQLite), so it runs in an **Expo
development build**, not Expo Go. Builds run in the cloud with EAS; no local Android Studio or Xcode is needed.
Nothing here is configured yet: every account and credential below is listed under "Needs credentials" in
PROGRESS.md.

## One-time setup (a human with the accounts)

1. **Expo account** (organisation-owned, not personal): `npx eas-cli@latest login`, then in `apps/driver-mobile`:
   `npx eas-cli@latest init` (writes the EAS project id into `app.json`; commit it).
2. **App identifiers:** `com.corridor.driver` is a placeholder (D-037). Change `android.package` and
   `ios.bundleIdentifier` in `app.json` to the organisation's reverse domain **before the first store build**:
   it cannot be changed after publishing.
3. **Android signing:** on the first `eas build -p android`, let EAS generate and store the upload keystore.
   Download a backup (`eas credentials`) and keep it in the company password manager. Losing it blocks updates.
4. **Google Play:** create the app in Play Console, complete the **background location declaration** (Play
   policy requires a video and justification for `ACCESS_BACKGROUND_LOCATION`), and create a service account
   key for `eas submit` (stored in EAS, never in the repo).
5. **Apple (only if iOS is in scope):** Apple Developer Program membership; EAS manages certificates and
   provisioning profiles. App Store review requires the "Always" location justification shown in `app.json`.
6. **Environment values:** set per profile in EAS (Project → Environment variables), not in the repo:
   `EXPO_PUBLIC_API_BASE_URL`, `EXPO_PUBLIC_AUTH_CLIENT_ID` (Cognito driver-mobile app client),
   `EXPO_PUBLIC_AUTH_AUTHORIZE_URL`, `EXPO_PUBLIC_AUTH_TOKEN_URL` (Cognito hosted domain). `EXPO_PUBLIC_*` values
   are compiled into the app and are public by design; the app has **no client secret**.
7. **Cognito:** register `corridor-driver://auth/callback` as a callback URL of the driver-mobile app client.
8. **Sentry for React Native (optional for the pilot):** create a project and add the DSN as an EAS variable.

## Builds

| Profile | Command | Use |
|---|---|---|
| development | `npx eas-cli@latest build --profile development --platform android` | device testing against a local/LAN API (`docs/mobile/device-test-plan.md`) |
| preview | `npx eas-cli@latest build --profile preview --platform android` | internal testers against staging |
| production | `npx eas-cli@latest build --profile production --platform android` then `npx eas-cli@latest submit -p android` | Play Store |

Local development without EAS: `npx expo run:android` (needs the Android SDK on the machine).

## Network notes

- Android emulator → host machine API: `http://10.0.2.2:8000` (the development profile default).
- Physical phone on the LAN: use the machine's LAN IP. Release builds require HTTPS (staging/production).
