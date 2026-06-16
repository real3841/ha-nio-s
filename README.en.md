# ha-nio-s

[简体中文](README.md) | **English**

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![release](https://img.shields.io/github/v/release/real3841/ha-nio-s)](https://github.com/real3841/ha-nio-s/releases)

Home Assistant custom integration for **NIO** electric vehicles
(EC6 / ES6 / ES8 / ET5 / ET7 …), built on the same private API the NIO iOS app
uses. There is no official NIO integration — this one gives you battery, range,
doors/windows, driving state, seat heating, off-car modes and a live map
position (GCJ-02 → WGS-84 corrected, no offset in mainland China), plus
**optional** battery-swap / service-order history.

![card](images/nio_card.png)

## Highlights

- **Vehicle status**: battery, range, vehicle state, charging, temperature, mileage, tyres, firmware
- **Door/window safety**: per-opening state for doors, windows, lock, frunk, tailgate, charge port
- **Alerts roundup**: doors/windows open, unlocked, low battery, offline, maintenance — rolled into one `Alerts` entity (ready for notifications)
- **Seat heating / ventilation & off-car modes**: steering-wheel heat, seat heat, pet / camping / defender modes
- **Live location**: registry-backed `device_tracker`, coordinates corrected, survives restarts
- **Battery swap / service orders (optional)**: swap counts, total/average spend, flexible upgrades, last order time
- **Bundled Lovelace card**: NIO Car Card — auto-registered, visual editor, zero frontend dependencies

## Two config types (added separately)

Vehicle status and swap history use **different APIs**, so they are added as two
independent entries that don't affect each other:

1. **Vehicle status** (required, works on its own)
2. **Battery swap / service orders** (optional)

Each entry has its own token, polling interval and "refresh now" button.

## Entities

### Vehicle (first add)

| Platform | Entities |
| --- | --- |
| `sensor` | Battery %, Range (CLTC), Range (actual), Range achievement rate, Full-charge range, Battery pack, Vehicle state, Charge state, Charging power, Inside/Outside temperature, Mileage, Steering-wheel heat, Front/Rear seat heat, Seat ventilation, Maintenance, Consecutive driving days, Alerts, Tyre pressure ×4 (diagnostic), Firmware version (diagnostic) |
| `binary_sensor` | Driving, Sleeping, Doors, Windows, Lock, Charging, Frunk, Tailgate, Charge port, Air conditioner, Alert active, Battery critical, Battery low, Maintenance due, Server alarm, Pet / Power-hold / Camping / Defender / Remote-video modes, Cloud / ADC / CDC connection (diagnostic) |
| `device_tracker` | Vehicle location (WGS-84, registry-backed — survives restarts) |
| `button` | Refresh data (immediate poll) |

`Alerts` (`sensor.*_alerts`) holds the count of alerts worth attention; its
`items` attribute carries the full list (title, detail, severity) — ready to
drive automations or a card.

Polling is adaptive to be gentle on the private API (it rate-limits, and may
invalidate your token, if hammered): every 5 min while driving, 15 min in the
daytime, 30 min overnight. All intervals are configurable in the options.

### Battery swap / service orders (second add, optional)

| Platform | Entities |
| --- | --- |
| `sensor` | Service orders total, Battery swaps completed, Battery swaps cancelled, Battery swap spend, Battery swap average spend, Flexible upgrades completed, Flexible upgrade spend, Last service order |
| `button` | Refresh service orders |

Defaults to polling every 60 minutes, configurable in the options.

## Lovelace card

The integration ships a custom card — **NIO Car Card** — and registers it
automatically (no manual Lovelace resource, no extra HACS frontend install).
After the integration loads, it appears in *Add card* as **NIO Car Card**.

It shows the official factory render for your car, a glass status bar (title +
CLTC range), five state icons (battery / driving / sleeping / doors / windows,
with red alerts when a door or window is open), and a tap-to-open popup with the
full status breakdown plus a refresh button.

Everything is set in the **visual editor** — pick the car (NIO device), model
and body colour from swatches; no YAML required:

| Option | Effect |
| --- | --- |
| Vehicle | The NIO device — entities are resolved from its registry, so renamed entity ids keep working |
| Model / Colour | Selects the bundled render; multiple models, every factory colour |
| Name | Card title (defaults to `NIO <MODEL>`) |
| Background colour | Studio backdrop tint behind the (transparent) car |
| Background gradient | Top-left-light → bottom-right-dark studio sheen (on by default) |
| Bar colour / opacity | Status-bar colour and translucency; icon/text colour auto-inverts for contrast |
| Show labels | State text under each icon; the bar auto-grows and the car scales to never be covered |
| Background image URL | Optional — overrides the backdrop colour with your own image |

Zero frontend dependencies: the popup, styling and editor are all self-contained
(no `card_mod` / `browser_mod` / `streamline-card`). A plain `picture-glance`
fallback snippet is in [`lovelace/`](lovelace/) for anyone who prefers raw YAML.

> [!NOTE]
> Car renders are the manufacturer's official press/configurator images,
> bundled for convenience and trimmed/feathered for the card. They remain the
> property of NIO Inc.; this project claims no rights over them.

## Installation

### HACS (custom repository)

1. HACS → Integrations → ⋮ → *Custom repositories*
2. Add `https://github.com/real3841/ha-nio-s` as type *Integration*
3. Install **NIO**, restart Home Assistant

### Manual

Copy `custom_components/nio/` into your HA `config/custom_components/` and
restart.

## Setup: vehicle status

The integration authenticates by replaying the app's own request, so you need
to sniff it once:

1. Put an MITM proxy (mitmproxy / Reqable / Charles / Surge / Quantumult X…)
   between your phone and the internet, trust its CA certificate.
2. Open the NIO app, pull-to-refresh the vehicle page.
3. Find the request to
   `https://icar.nio.com/api/2/rvs/vehicle/<vehicle_id>/status?...`
4. Grab two things:
   - the **whole request URL** (from `https://…/status?` through the trailing
     `…&sign=…` — copy all of it)
   - the token — the `Authorization: Bearer …` request **header**
5. In HA: *Settings → Devices & services → Add integration → NIO → Vehicle
   status*, paste the whole URL into the "Status request URL" box, the token
   into the token box, and set your model.

> [!IMPORTANT]
> **Don't edit that URL.** The server's `sign` covers the entire query string
> (field list + order, `app_ver`, `device_id`, `timestamp`…), and those drift
> across app versions (6.6.0 added `field=key`; `app_ver` differs per user). The
> integration replays your captured URL **byte-for-byte**, so don't reconstruct
> it field-by-field. The captured `sign` isn't freshness-checked, so one capture
> lasts a long time. URL and token are kept in HA's encrypted config storage
> (no plaintext YAML).

> [!WARNING]
> The Bearer token is your NIO account session credential — treat it like a
> password. This integration is **read-only** (it never sends commands), but
> the token itself would allow remote vehicle control elsewhere.

When the token eventually expires, HA raises a re-authentication notification —
sniff a fresh token and enter it. No restart needed. If the prompt says the
**signature** was rejected (usually after an app update), also paste a freshly
captured URL to refresh it.

## Setup: battery swap / service orders (optional)

Swap history uses a different endpoint
(`gateway-front-external.nio.com/.../serviceOrder/getTabOrder`). Copying the
**full request from Postman** is usually easiest:

1. In Postman (or a proxy), prepare the getTabOrder request, make sure **all the
   Params are present** (`limit`, `orderTypes`, `region`, …), and confirm
   **Send** returns the order list.
2. Copy:
   - the **full URL** (including every query param after `?`)
   - the **Bearer token** (Authorization tab)
3. In HA: *Add integration → NIO → Battery swap / service orders*, fill in:
   - **getTabOrder request URL**
   - **Bearer token**
   - **HTTP method** (defaults to `POST`, empty body)
   - **Cookie / User-Agent / mobileinfo**: optional — most Postman captures
     don't need them, leave blank

> [!TIP]
> If all swap sensors read 0, the URL was probably **pasted without its query
> params** (everything after `?`) or the **token doesn't match**. Open the
> `Service orders` sensor and check:
> - `api_result_code` is `0000` (success)
> - `http_status` is `200`, `http_method` is `POST`
> - `raw_order_count` > 0 (orders returned by the API)
> - `swap_order_count` is battery-swap orders only (`service_orders_total` includes maintenance, etc.)
>
> Tap **Refresh service orders**, then re-check attributes; or enable
> `custom_components.nio.change_api: debug` in `configuration.yaml` and read the HA log.

## Notes

- **Coordinate correction**: positions from the API are GCJ-02 (mandatory
  obfuscation in mainland China). The device tracker converts to WGS-84
  in-process using the standard 7-parameter approximation, so HA's map shows
  the true position.
- **Door semantics** are field-tested on a real EC6 (every opening cycled and
  matched 1:1 against raw API captures): `*_ajar_status` `1` = closed, `0` =
  open; `vehicle_lock_status` `1` = locked, `0` = unlocked. Window `win_*_posn`
  is `0` = closed, `>0` = open. If your car reports differently, please open an
  issue with the `door_status` payload.
- **Alerts**: `sensor.*_alerts` already bundles the door/lock/low-battery/
  offline/maintenance/defender rules — no templates needed. Listen to it to
  drive notifications.

## Acknowledgements

This project extends **[genelee26](https://github.com/genelee26/ha-nio)'s** ha-nio
integration. Thank you for turning the scattered-YAML approach into a full HACS
integration and open-sourcing the Lovelace card and capture-replay setup.

The original idea — sniffing the NIO app's private API and feeding it into Home
Assistant — comes from **pangjian**'s 2022 post on the Hassbian forum,
[《蔚来接入HA 抛砖引玉》](https://bbs.hassbian.com/thread-17594-1-1.html).
Thank you, pangjian. 🙏

## Disclaimer

Not affiliated with NIO Inc. Uses an undocumented private API that may change
or break at any time. Use at your own risk.
