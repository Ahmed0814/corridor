import { registerRootComponent } from 'expo';

// The background location task must be defined at module load, before the app registers: when the
// OS wakes the app for a location update, only module code runs (no component mounts).
import './src/tracking/task';

import App from './App';

registerRootComponent(App);
