import { StatusBar } from 'expo-status-bar';
import { StyleSheet, Text, View } from 'react-native';

// Phase 1 shell. Sign-in, trips, background tracking and the offline queue arrive in
// Phase 5. Until then this screen must not imply that anything is being tracked
// (MASTER_PROMPT §4.2: never pretend background GPS is running).
export default function App() {
  return (
    <View style={styles.container} accessibilityRole="summary">
      <Text style={styles.title}>Corridor Driver</Text>
      <Text style={styles.status} accessibilityLabel="Tracking status: not available">
        Tracking: not available in this build
      </Text>
      <Text style={styles.note}>Development shell. No location is collected.</Text>
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
    gap: 8,
  },
  title: { fontSize: 22, fontWeight: '600' },
  status: { fontSize: 16 },
  note: { fontSize: 14, color: '#555', textAlign: 'center' },
});
