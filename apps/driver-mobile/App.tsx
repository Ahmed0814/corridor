import * as AuthSession from 'expo-auth-session';
import { StatusBar } from 'expo-status-bar';
import * as WebBrowser from 'expo-web-browser';
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { ApiError, fetchMe } from './src/api';
import { describeError, toStoredSession, type Me } from './src/auth/session';
import { clearSession, loadSession, saveSession } from './src/auth/tokenStore';
import { TripsScreen } from './src/screens/TripsScreen';
import { getEngine } from './src/tracking/runtime';
import { AUTH } from './src/config';

// Completes the auth session when the redirect returns to the app (required by expo-auth-session).
WebBrowser.maybeCompleteAuthSession();

const discovery = {
  authorizationEndpoint: AUTH.authorizationEndpoint,
  tokenEndpoint: AUTH.tokenEndpoint,
};

type State =
  | { kind: 'loading' }
  | { kind: 'signedOut'; message?: string }
  | { kind: 'signedIn'; me: Me };

// Phase 2: sign-in only. Trips, background tracking and the offline queue arrive in Phase 5.
// Until then the app must not imply that anything is being tracked (MASTER_PROMPT §4.2).
export default function App() {
  const [state, setState] = useState<State>({ kind: 'loading' });
  const redirectUri = AuthSession.makeRedirectUri({ scheme: AUTH.redirectScheme, path: AUTH.redirectPath });
  const [request, , promptAsync] = AuthSession.useAuthRequest(
    {
      clientId: AUTH.clientId,
      redirectUri,
      scopes: [...AUTH.scopes],
      responseType: AuthSession.ResponseType.Code,
      usePKCE: true,
    },
    discovery,
  );

  const showProfile = useCallback(async (session: Awaited<ReturnType<typeof loadSession>>) => {
    if (!session) {
      setState({ kind: 'signedOut' });
      return;
    }
    try {
      const { me } = await fetchMe(session);
      getEngine().resumeAfterSignIn();
      setState({ kind: 'signedIn', me });
    } catch (error) {
      const code = error instanceof ApiError ? error.code : null;
      if (code === 'unauthenticated') await clearSession();
      setState({ kind: 'signedOut', message: describeError(code) });
    }
  }, []);

  // Restore a saved session on launch.
  useEffect(() => {
    loadSession().then(showProfile, () => setState({ kind: 'signedOut' }));
  }, [showProfile]);

  // Open the system browser, then finish the authorization-code + PKCE exchange with the result.
  const signIn = async () => {
    const result = await promptAsync();
    if (result.type === 'error') {
      setState({ kind: 'signedOut', message: describeError(null) });
      return;
    }
    if (result.type !== 'success' || !request?.codeVerifier) return; // cancelled or dismissed
    setState({ kind: 'loading' });
    try {
      const token = await AuthSession.exchangeCodeAsync(
        {
          clientId: AUTH.clientId,
          code: result.params.code,
          redirectUri,
          extraParams: { code_verifier: request.codeVerifier },
        },
        discovery,
      );
      const session = toStoredSession(token, Date.now());
      await saveSession(session);
      await showProfile(session);
    } catch {
      setState({ kind: 'signedOut', message: describeError(null) });
    }
  };

  const signOut = async () => {
    await clearSession();
    setState({ kind: 'signedOut' });
  };

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Corridor Driver</Text>

      {state.kind === 'loading' && <ActivityIndicator accessibilityLabel="Loading" />}

      {state.kind === 'signedOut' && (
        <>
          {state.message && (
            <Text style={styles.error} accessibilityRole="alert">
              {state.message}
            </Text>
          )}
          <Pressable
            accessibilityRole="button"
            disabled={!request}
            onPress={signIn}
            style={({ pressed }) => [styles.button, (!request || pressed) && styles.buttonDim]}
          >
            <Text style={styles.buttonText}>Sign in</Text>
          </Pressable>
        </>
      )}

      {state.kind === 'signedIn' && (
        <View style={styles.signedIn}>
          <View style={styles.header}>
            <View>
              <Text style={styles.name}>{state.me.display_name || 'Driver'}</Text>
              <Text style={styles.detail}>
                {state.me.active_tenant ? state.me.active_tenant.tenant_name : 'No company'}
              </Text>
            </View>
            <Pressable accessibilityRole="button" onPress={signOut} style={styles.linkButton}>
              <Text style={styles.link}>Sign out</Text>
            </Pressable>
          </View>
          {/* Location is collected only while a trip is active (consent shown before starting). */}
          <TripsScreen />
        </View>
      )}

      <StatusBar style="auto" />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 24,
    gap: 12,
  },
  title: { fontSize: 22, fontWeight: '600' },
  name: { fontSize: 18, fontWeight: '600' },
  detail: { fontSize: 16, color: '#333' },
  error: { fontSize: 15, color: '#b00020', textAlign: 'center' },
  button: { backgroundColor: '#1f2937', paddingVertical: 14, paddingHorizontal: 20, borderRadius: 8 },
  buttonDim: { opacity: 0.6 },
  buttonText: { color: '#fff', fontSize: 16, fontWeight: '600' },
  linkButton: { padding: 8 },
  link: { fontSize: 16, color: '#1f4fd1', textDecorationLine: 'underline' },
  signedIn: { flex: 1, width: '100%', paddingTop: 48 },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 16 },
});
