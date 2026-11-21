# Driver app — device test plan (Phase 5)

The offline queue and sync engine are verified automatically (`apps/driver-mobile`: `npm test`, plus
`scripts/sync-against-api.mts` against a real API). What only a phone can prove is listed here: background
GPS, OS restrictions, real network loss, battery behaviour. **A human runs this plan and signs it off in
PROGRESS.md. Production release waits for that sign-off** (MASTER_PROMPT §0.4).

## Devices (minimum)

| # | Device | Why |
|---|---|---|
| A | Tecno or Infinix (HiOS/XOS), Android 12+ | very common in Djibouti/Ethiopia; aggressive background killing |
| B | Samsung (One UI), Android 13+ | "Sleeping apps" / deep sleep behaviour |
| C | Any Android 14+ phone | `FOREGROUND_SERVICE_LOCATION` rules |
| D | Android emulator (API 34, Google APIs image) | scripted network loss and mock locations |
| E | iPhone (iOS 17+), only if iOS is in pilot scope | background location indicator, "Always" permission |

## Setup

1. Build: `npx eas-cli@latest build --profile development --platform android` (see `docs/mobile/build-and-credentials.md`). Install the APK.
2. Backend reachable from the phone: run the stack on a LAN machine and set `EXPO_PUBLIC_API_BASE_URL` to its LAN IP, or use staging once it exists.
3. In the web app (`/ops`): create a demo company, a vehicle, a driver profile, invite the driver's phone number, link the profile, then create, confirm and dispatch a shipment with that vehicle and driver.
4. On the phone: sign in with the driver's phone number. The trip appears under "Trips".

Record for every case: device, OS version, app build, date, tester, PASS/FAIL, notes/screenshots.

## Cases

| ID | Case | Steps | Pass criteria |
|---|---|---|---|
| D1 | Permission flow | Tap "Start trip" on a fresh install | Foreground prompt, then background ("Allow all the time"). If background is refused, the status card shows the warning and "Tracking" is not shown as Active after the screen is off |
| D2 | Foreground service | Start trip, lock the screen for 10 min | Persistent notification "Corridor Driver: trip tracking on" stays; the `/ops/map` vehicle stays LIVE (green) |
| D3 | Moving cadence | Drive or walk ≥ 2 km with the screen off | Points every ~20 s while moving; track in `GET /trips/{id}/locations` has no gaps > 60 s |
| D4 | Stationary cadence | Park 10 min | About one point per 2 min; the vehicle does not go STALE |
| D5 | Network loss | Airplane mode 15 min while moving, then off | During: status "Waiting for network", "Waiting to upload" grows. After: uploads within 1 min, the counter returns to 0, the server track is continuous (no missing interval) |
| D6 | App killed by user | Swipe the app away during a trip | Either the foreground service keeps tracking, or the status card on reopen shows "Tracking: Stopped" with the alert. It must NEVER show Active while stopped. Points recorded before the kill are uploaded |
| D7 | Phone restart | Reboot during a trip with queued points (airplane mode on) | After reboot and reopening: queued points are still there and upload; tracking can be restarted from the trip |
| D8 | OEM battery killer | On A and B, leave the default battery settings for 1 h | Record whether tracking stops. Then apply the in-app "Keep tracking alive" steps and repeat; tracking must survive 1 h |
| D9 | Interrupted upload | Toggle airplane mode on during "Synchronising…" | No duplicate points on the server (count `GET /trips/{id}/locations`), no points lost |
| D10 | Large backlog | Airplane mode for 4 h of driving (or emulator D below), then reconnect | All points upload; the app stays responsive; the server has every point exactly once |
| D11 | Pause / resume | Pause the trip 5 min, resume | Points while paused are flagged `while_paused` server-side; tracking continues after resume |
| D12 | Complete trip | Complete the trip while some points are queued | Queue uploads before tracking stops; the notification disappears; the map shows OFFLINE for the vehicle |
| D13 | Sign-out / token expiry | Revoke or expire the session mid-trip | Status "Sign-in needed"; points are kept; after sign-in they upload |
| D14 | Mock location | Enable a mock-location app (emulator: send fake GPS) | Mocked fixes are not recorded; the status card warns |
| D15 | Battery use | 8 h trip on device A | Record battery drop per hour (target: under 6 %/h with screen off) |
| D16 | Low accuracy indoors | Start inside a building | Points with accuracy > 100 m are stored but never become the vehicle's latest position on the map |

## Emulator script (device D)

- Network loss: `adb shell svc wifi disable && adb shell svc data disable`, wait, then re-enable.
- Restart: `adb shell am force-stop com.corridor.driver`, then reopen; and `adb reboot`.
- Route playback: Android Studio → Extended controls → Location → Routes (a GPX along Djibouti → Galafi), speed ×4.
- Large backlog (D10): play the route for 2 h of simulated time with networking disabled, then enable it.
- Mock location: playback of extended controls marks fixes as mocked on some images. Verify D14 with a mock-location app as well.

## Sign-off (fill in)

| Device | OS | Build | Cases passed | Failed (IDs) | Tester | Date |
|---|---|---|---|---|---|---|
| A |  |  |  |  |  |  |
| B |  |  |  |  |  |  |
| C |  |  |  |  |  |  |
| D (emulator) |  |  |  |  |  |  |
| E (iOS, if in scope) |  |  |  |  |  |  |

Android is required for the pilot; iOS only if it is in scope (MASTER_PROMPT Phase 5).
