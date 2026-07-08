# Grünbeck softliQ Cloud — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/ironbiff/ha-gruenbeck-softliq.svg)](https://github.com/ironbiff/ha-gruenbeck-softliq/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A Home Assistant custom integration for **Grünbeck softliQ** water softeners
(SD/SE series, e.g. softliQ:SD18) connected to the **myGrünbeck cloud**.

The integration talks directly to the Grünbeck cloud API — the same API the
myGrünbeck mobile app uses. No ioBroker, MQTT bridge or local gateway is
required. Realtime values are pushed over a SignalR websocket, so flow rate
and regeneration status update within seconds.

> [!NOTE]
> This is a private project and is **not** affiliated with, sponsored or
> endorsed by Grünbeck Wasseraufbereitung GmbH.

## Features

- **Config flow (UI setup)** — sign in with your myGrünbeck account,
  no YAML required
- **Cloud push** — live values via websocket (flow rate, remaining
  capacity, regeneration progress, …)
- **Sensors**
  - Flow rate (m³/h)
  - Soft water quantity (L, suitable for the water dashboard)
  - Remaining capacity (m³ and %)
  - Salt range (days) and total salt consumption (kg)
  - Daily salt (kg) and water (L) consumption incl. history attribute
  - Next regeneration (timestamp), regeneration step/progress/counter
  - Days until next maintenance, startup date
- **Binary sensors** — regeneration running, device problem
- **Controls**
  - Start regeneration / start boost mode (buttons)
  - Operating mode: Eco / Comfort / Power / Individual (select)
  - Raw water hardness and soft water hardness setpoint (numbers)
- **Diagnostics** download with redacted personal data, re-auth flow when
  the password changes

Entities for a second exchanger (SE series) are created automatically when
the device reports them.

## Requirements

- A softliQ device that is registered in the [myGrünbeck app](https://www.gruenbeck.de/)
  and connected to the Grünbeck cloud
- Home Assistant 2024.12 or newer

## Installation

### HACS (recommended)

1. In HACS, open the ⋮ menu → **Custom repositories**
2. Add `https://github.com/ironbiff/ha-gruenbeck-softliq` with type
   **Integration**
3. Search for **Grünbeck softliQ Cloud** in HACS and download it
4. Restart Home Assistant

### Manual

1. Copy the folder `custom_components/gruenbeck_softliq` of this repository
   into the `custom_components` folder of your Home Assistant configuration
   directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings → Devices & services → Add integration**
2. Search for **Grünbeck softliQ Cloud**
3. Enter the **email address and password of your myGrünbeck account**

The integration discovers the softliQ device of the account automatically
and creates one Home Assistant device with all entities.

### Options

**Settings → Devices & services → Grünbeck softliQ Cloud → Configure**

| Option | Default | Description |
| --- | --- | --- |
| Polling interval | 360 s | How often the realtime session is refreshed. **Do not go below 360 s** — the Grünbeck cloud temporarily blocks accounts that poll faster. |

Live values arrive over the websocket independently of this interval.
Device information and parameters are refreshed hourly, the daily salt and
water statistics every 8 hours.

## Notes & known limitations

- The cloud only accepts one realtime session per account at a time. If the
  myGrünbeck app is open at the same moment, values may pause briefly.
- Grünbeck did not publish this API; it was reverse engineered from the
  mobile app. It may change without notice.
- If your device has the LED ring configured to "operation by user", cloud
  polling counts as user operation and can keep the ring lit. Set the LED
  ring to light up only on faults if that bothers you.
- Only softliQ **SD/SE** models with cloud connectivity are supported. For
  the older SC series (local HTTP interface) see
  [gruenbeck_softliQ_SC](https://github.com/tizianodeg/gruenbeck_softliQ_SC).

## How it works

The integration implements three parts of the myGrünbeck protocol:

1. **Login** — OAuth2 authorization-code flow with PKCE against Grünbeck's
   Azure AD B2C tenant (`gruenbeckb2c.b2clogin.com`), using the app's
   client id. Tokens are refreshed automatically.
2. **REST API** — `prod-eu-gruenbeck-api.azurewebsites.net` for the device
   list, device details, parameters (read/write), daily measurements and
   the regenerate/boost commands.
3. **Realtime push** — a SignalR websocket
   (`prod-eu-gruenbeck-signalr.service.signalr.net`) that pushes
   measurement updates. The device is kept in realtime mode by calling the
   `realtime/enter` + `realtime/refresh` endpoints on every polling cycle.

## Credits

- Protocol analysis based on the ioBroker adapter
  [TA2k/ioBroker.gruenbeck](https://github.com/TA2k/ioBroker.gruenbeck)
- Related projects: [p0l0/pygruenbeck_cloud](https://github.com/p0l0/pygruenbeck_cloud)
  and [p0l0/hagruenbeck_cloud](https://github.com/p0l0/hagruenbeck_cloud)

## License

[MIT](LICENSE)

---

## Kurzanleitung (Deutsch)

Diese Integration verbindet Home Assistant **direkt** mit der
myGrünbeck-Cloud — ioBroker und MQTT werden nicht mehr benötigt.

1. Repository in HACS als benutzerdefiniertes Repository hinzufügen
   (Typ *Integration*), Integration herunterladen, Home Assistant neu
   starten
2. **Einstellungen → Geräte & Dienste → Integration hinzufügen →
   „Grünbeck softliQ Cloud"**
3. Mit E-Mail und Passwort des myGrünbeck-Kontos anmelden

Danach erscheint die Enthärtungsanlage als Gerät mit allen Sensoren
(Durchfluss, Weichwassermenge, Salzreichweite, Restkapazität, nächste
Regeneration, …), Schaltern für Regeneration/Boost sowie einstellbarem
Betriebsmodus, Rohwasserhärte und Wunschhärte. Das Abfrageintervall darf
nicht unter 360 Sekunden liegen, sonst blockiert die Grünbeck-Cloud das
Konto vorübergehend.
