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
- **Long-Term Statistics (LTS):** Imports your full available consumption history from the ista portal into Home Assistant, allowing you to track usage over time in the Energy Dashboard or with history graphs.
- **Regular Updates:** Periodically fetches the latest readings to keep your sensors current.
- **Dynamic Entity Creation:** Automatically creates and adds sensors as they appear in your ista account.
- **Configurable Options:** Adjust the update frequency and log level directly from the UI.
- **Re-authentication Flow:** Notifies you and prompts for a new password if your credentials expire.
- **Reconfiguration Flow:** Change your account email, password, or historical data start date at any time without removing the integration.

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
    - Download the latest release from the [Releases](https://github.com/herruzo99/ista-calista/releases) page.
    - Copy the `custom_components/ista_calista` directory into your Home Assistant `<config>/custom_components` folder.
    - Restart Home Assistant.

## Configuration

1.  Navigate to **Settings** > **Devices & Services**.
2.  Click **Add Integration** and search for **"Ista Calista"**.
3.  Enter your ista Calista portal **email** and **password**.
4.  **Consumption Start Date:** Select the date from which to import historical data. The portal typically provides data for the last 1-2 years. The default is one year ago.
5.  Click **Submit**.

The integration will perform an initial data sync, which may take several minutes depending on the amount of history available.

## Provided Entities

Each physical meter on your account creates a **device** in Home Assistant with the following entities:

| Entity | Unit | Description |
|--------|------|-------------|
| Heating | kWh | Current meter reading for heating consumption |
| Hot Water | m³ | Current meter reading for hot water consumption |
| Water | m³ | Current meter reading for cold water consumption |
| Last Measured Date | — | Timestamp of the most recent reading (diagnostic, disabled by default) |

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

## Known Limitations

- **Spain only:** This integration connects to the Spanish ista portal (`oficina.ista.es`). Other regional portals are not supported.
- **Polling only:** Data is not pushed in real time. The integration polls the portal on a schedule (minimum 1 hour, default 24 hours). Readings from the portal itself may be delayed by days depending on your meter type.
- **Historical data window:** The ista portal typically retains 1–2 years of history. Data older than that cannot be retrieved.
- **No meter control:** This is a read-only integration. It cannot submit readings or interact with your meters in any way.
- **Single account per instance:** Each integration entry corresponds to one ista account. If you have meters under multiple accounts, add the integration again for each account.

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

## Contributing

Contributions to this project are welcome! Please follow standard development practices: lint your code, add tests for new functionality, and ensure existing tests pass. Use the Nix development environment to ensure consistency.

## Disclaimer

This is an unofficial, third-party integration. It is not affiliated with, authorized, maintained, sponsored, or endorsed by ista International GmbH. Use this at your own risk. The developer is not responsible for any issues or damages that may arise from its use.
