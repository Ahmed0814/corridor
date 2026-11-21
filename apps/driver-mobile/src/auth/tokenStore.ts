import * as SecureStore from 'expo-secure-store';

import { parseStoredSession, type StoredSession } from './session';

// Android Keystore / iOS Keychain via expo-secure-store (security-model.md §2). Never AsyncStorage.
const KEY = 'corridor.session.v1';

export async function loadSession(): Promise<StoredSession | null> {
  return parseStoredSession(await SecureStore.getItemAsync(KEY));
}

export async function saveSession(session: StoredSession): Promise<void> {
  await SecureStore.setItemAsync(KEY, JSON.stringify(session));
}

export async function clearSession(): Promise<void> {
  await SecureStore.deleteItemAsync(KEY);
}
