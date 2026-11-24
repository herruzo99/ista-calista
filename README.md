# Home Assistant Ista Calista Integration

[![GitHub CI](https://github.com/herruzo99/ista-calista/actions/workflows/tests.yml/badge.svg)](https://github.com/herruzo99/ista-calista/actions/workflows/tests.yml)
[![Validation](https://github.com/herruzo99/ista-calista/actions/workflows/validate.yml/badge.svg)](https://github.com/herruzo99/ista-calista/actions/workflows/validate.yml)
[![codecov](https://codecov.io/gh/herruzo99/ista-calista/branch/main/graph/badge.svg)](https://codecov.io/gh/herruzo99/ista-calista)
[![HACS Badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub License](https://img.shields.io/github/license/herruzo99/ista-calista)](https://github.com/herruzo99/ista-calista/blob/main/LICENSE)

This Home Assistant custom component integrates with the [ista Calista portal](https://oficina.ista.es/) to monitor your heating and water consumption. It provides sensors for your various meters and records historical data using Home Assistant's Long-Term Statistics feature.

**Note:** This integration currently supports the Spanish (ista.es) portal.

[![Open your Home Assistant instance and open a repository inside the HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=herruzo99&repository=ista-calista)

---

## Features

- **Multi-Meter Support:** Retrieves data for all supported meter types on your account:
  - Heating (kWh)
  - Hot Water (m³)
  - Cold Water (m³)
- **LTS & Billing History:** Imports your full available consumption history AND billing/invoice data into Home Assistant.
- **Seasonal Analysis:** Tracks your consumption across different seasons (e.g., Heating Season).
- **Invoice Management:** Provides sensors for your latest invoice details and a service to download PDF bills directly.
- **Dynamic Entity Creation:** Automatically creates and adds sensors as they appear in your ista account.

## Prerequisites

- An active account on the [ista Calista portal](https://oficina.ista.es/).
- Home Assistant (Version 2026.3.0 or newer).
- HACS (Home Assistant Community Store) installed.

## Installation

1.  **Install via HACS (Recommended):**
    - Go to HACS > Integrations.
    - Click the three dots in the top right and select "Custom repositories".
    - Add the URL `https://github.com/herruzo99/ista-calista` with the category "Integration".
    - Find the "Ista Calista" integration in the list and click "Install".
    - Restart Home Assistant when prompted.

2.  **Manual Installation:**
    - Download `ista_calista.zip` from the assets of the latest [Release](https://github.com/herruzo99/ista-calista/releases).
    - Extract the archive and copy the `custom_components/ista_calista` directory into your Home Assistant `<config>/custom_components` folder.
    - Restart Home Assistant.

## Configuration

1.  Navigate to **Settings** > **Devices & Services**.
2.  Click **Add Integration** and search for **"Ista Calista"**.
3.  Enter your ista Calista portal **email** and **password**.
4.  **Consumption Start Date:** Select the date from which to import historical data.
5.  **Heating Season Start:** Select the day and month when your heating season typically begins (used for seasonal consumption calculation).
6.  Click **Submit**.

## Provided Entities

The integration creates a **device** for each physical meter, plus a global integration device for account-wide data.

### Meter Entities
| Entity | Unit | Description |
|--------|------|-------------|
| Heating | kWh | Current meter reading for heating consumption |
| Hot Water | m³ | Current meter reading for hot water consumption |
| Water | m³ | Current meter reading for cold water consumption |
| Average Daily Consumption | — | Calculated average based on historical data |
| Seasonal Consumption | — | Consumption since the start of the current season |

### Billing & Invoice Entities (Global)
| Entity | Unit | Description |
|--------|------|-------------|
| Latest Invoice ID | — | The identification number of your most recent bill |
| Latest Invoice Amount | € | The total amount of your latest invoice |
| Billed Reading Date | — | The date of the last officially billed reading |
| Billed Reading | — | The value of the last officially billed reading |
| Individual Bill (Multiple) | — | Binary sensors for each recent invoice with details in attributes |

All consumption sensors feed directly into Home Assistant's **Long-Term Statistics**, making them available in the **Energy Dashboard** and compatible with history graphs.

## How Data Is Updated

On first setup, the integration fetches the full consumption history starting from your chosen **Consumption Start Date**. This is a one-time operation and may take a moment.

On every subsequent update (default: every 24 hours), the integration fetches the last 30 days of readings. New readings are merged with the existing history, so no data is ever lost. Only net-new readings are pushed into Long-Term Statistics.

## Options

After setup, you can adjust the integration's options:

1.  Navigate to the Ista Calista integration on the **Devices & Services** page.
2.  Click **Configure**.
3.  Adjust the **Update Interval** (1–168 hours) and **Log Level** as needed.

To change your account credentials or start date, click the **three dots** next to the integration and select **Reconfigure**.

## Use Cases

- **Energy Dashboard:** Add your heating (kWh) and water (m³) sensors to the Home Assistant Energy Dashboard to track consumption and costs over time alongside your electricity and gas usage.
- **Monthly Budget Alerts:** Create an automation that sends a notification if your monthly heating consumption exceeds a set threshold.
- **Consumption Graphs:** Use the history graph card or Apexcharts to visualize daily, monthly, or yearly consumption trends.
- **Comparative Analysis:** Compare heating consumption across different months or years to identify seasonal patterns or the effect of home improvements.

## Automation Examples

### Alert when monthly heating exceeds a threshold

```yaml
automation:
  - alias: "High heating consumption alert"
    trigger:
      - platform: numeric_state
        entity_id: sensor.living_room_heating
        above: 500
    action:
      - service: notify.mobile_app
        data:
          message: "Heating consumption has exceeded 500 kWh this period."
```

### Log daily water reading

```yaml
automation:
  - alias: "Log daily water reading"
    trigger:
      - platform: time
        at: "23:55:00"
    action:
      - service: logbook.log
        data:
          name: "Daily Water Reading"
          message: "{{ states('sensor.kitchen_water') }} m³"
```

## Multi-property support (experimental)

One ista email can be linked to several portal properties. Each property needs
its own integration entry.

- Add the integration once per property. If the account holds one property, the
  entry is created without an extra step. If it holds several, the form asks
  which property the entry must read.
- The entry title and the account device show the property label. The property
  label can be an address.
- Each entry has a private session, its own cookie jar and its own property
  selection. The entry detaches its session on unload; it never closes a
  session that Home Assistant owns. Two properties never share a session or an invoice download.
- `ista_calista.get_invoices` returns the `entry_id`, `account_id`,
  `account_label` and `email` of every invoice, so you can tell properties
  apart. `ista_calista.download_invoice` uses the client that owns the invoice
  ID. If the same invoice ID exists on two properties, the service asks for
  `entry_id` (or `account_id`) and fails instead of guessing. If two properties hold an invoice with the same device type and date, the
  saved file name gets a short suffix, so the properties do not overwrite each
  other. One matching property keeps the old file name.
- Diagnostics redact the password, the property ID and the property label.
- Meter entities and their long-term statistics keep their serial based IDs.
  Account-level entities (invoice, bill, connection, refresh) use the property
  in their unique ID.

**Experimental status: synthetic two-property tests pass; only a live
single-property account was verified.** Two properties were tested with
synthetic fixtures, not on the live portal. The live check covered one
property only.

Limitations of this experimental release:

- Two properties that report the same meter serial number would collide on the
  meter entity unique IDs and on the statistic IDs. No live portal showed this.
- Existing account-level entity IDs change once after the upgrade to 0.10.0,
  because the property is now part of their unique ID. Long-term statistics of
  the meters do not change.
- A version 1 entry is migrated offline. If the account holds several
  properties, setup stops and asks for a reconfigure, because the property
  cannot be chosen without a login.

## Known Limitations

- **Spain only:** This integration connects to the Spanish ista portal (`oficina.ista.es`). Other regional portals are not supported.
- **Polling only:** Data is not pushed in real time. The integration polls the portal on a schedule (minimum 1 hour, default 24 hours). Readings from the portal itself may be delayed by days depending on your meter type.
- **Historical data window:** The ista portal typically retains 1–2 years of history. Data older than that cannot be retrieved.
- **No meter control:** This is a read-only integration. It cannot submit readings or interact with your meters in any way.
- **One property per entry:** Each integration entry reads one portal property. If your email holds several properties, add the integration again for each one (see below). Allow one private session and one polling cycle per entry.

## Troubleshooting

- **Authentication Failed:** Double-check your credentials. If the problem persists, log in to the official ista portal to confirm your password is correct. If you are notified of an authentication error in Home Assistant, go to the integration and select **Re-authenticate**.
- **Sensors Not Appearing:** After the initial setup, it can take a few minutes for the first data pull to complete. Check the Home Assistant logs for any errors related to `ista_calista`. Ensure the "Consumption Start Date" is set to a reasonable past date.
- **No History in Energy Dashboard:** Long-Term Statistics are imported asynchronously after each coordinator update. Wait a few minutes after the first successful update and then refresh the Energy Dashboard.
- **Checking Logs:** Set the **Log Level** to `Debug` in the integration options (under **Configure**) to get detailed output. Remember to set it back to `Info` once you are done troubleshooting to avoid log bloat.

For persistent issues, please [open an issue](https://github.com/herruzo99/ista-calista/issues) on GitHub and include any relevant logs.

## Removal

1.  Navigate to **Settings** > **Devices & Services**.
2.  Find the **Ista Calista** integration and click the **three dots** menu.
3.  Select **Delete**.

Removing the integration will delete all associated config entries. The Long-Term Statistics data recorded in your Home Assistant database will also be cleared automatically.

## Development

This project uses [Nix](https://nixos.org/) with [flakes](https://nixos.wiki/wiki/Flakes) to provide a reproducible development environment. All dependencies, including the correct Python version, Home Assistant test libraries, and linters, are defined in `flake.nix`.

### Prerequisites

1.  **Install Nix:** Follow the instructions at [nixos.org/download.html](https://nixos.org/download.html).
2.  **Enable Flakes:** Enable flakes by editing your Nix configuration.
    - For NixOS: Add `nix.settings.experimental-features = [ "nix-command" "flakes" ];` to your `configuration.nix`.
    - For other systems: Add `experimental-features = nix-command flakes` to `~/.config/nix/nix.conf`.

### Environment Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/herruzo99/ista-calista.git
    cd ista-calista
    ```

2.  **Activate the development shell:**
    ```bash
    nix develop
    ```
    The first time you run this command, Nix will download and build all the necessary dependencies. This may take some time. Subsequent runs will be much faster as the dependencies will be cached. Once complete, you will be in a shell with all the required tools available.

### Running Tests

The test suite is built using `pytest` and the `pytest-homeassistant-custom-component` library.

To run all tests:
```bash
pytest
```

To run a specific test file:
```bash
pytest tests/test_sensor.py
```

### Releases

Pushing a tag matching `v*` runs the [Release workflow](.github/workflows/release.yml). It packages `custom_components/ista_calista/` as `ista_calista.zip`, validates the archive, and uploads it to the GitHub Release. HACS is configured in `hacs.json` to download this asset, so its download counter reflects asset downloads rather than GitHub's automatic source archives.

To add the ZIP to an existing release without creating a new tag, run the **Release** workflow manually from the Actions tab and enter the existing tag (for example, `v0.9.2`). Re-running it replaces the ZIP asset while preserving the release.

## Contributing

Contributions to this project are welcome! Please follow standard development practices: lint your code, add tests for new functionality, and ensure existing tests pass. Use the Nix development environment to ensure consistency.

## Disclaimer

This is an unofficial, third-party integration. It is not affiliated with, authorized, maintained, sponsored, or endorsed by ista International GmbH. Use this at your own risk. The developer is not responsible for any issues or damages that may arise from its use.
