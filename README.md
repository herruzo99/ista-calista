# Home Assistant Integration for ista Calista Portal

[![hacs_badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://github.com/hacs/integration)
This integration allows you to monitor your heating and water consumption data from the [ista Calista portal](https://oficina.ista.es/) within Home Assistant.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=herruzo99&repository=ista-calista)
## Features

* Retrieves historical consumption data for:
    * Heating
    * Hot Water
    * Cold Water
* Provides sensors for the latest readings.
* Stores historical data as Long-Term Statistics (LTS) in Home Assistant.
* Configurable update interval via Options Flow.
* Supports multiple meter types associated with your account.

## Prerequisites

* An active account on the ista Calista portal.
* Home Assistant installation (Version 2023.1.0 or newer recommended).
* HACS (Home Assistant Community Store) installed.

## Installation

1.  **Via HACS (Recommended):**
    * Search for "Ista Calista" in the HACS integrations tab.
    * Click "Install".
    * Restart Home Assistant.
2.  **Manual Installation:**
    * Copy the `custom_components/ista_calista` directory to your Home Assistant `custom_components` folder.
    * Restart Home Assistant.

## Configuration

1.  Go to **Settings** -> **Devices & Services**.
2.  Click **Add Integration**.
3.  Search for "Ista Calista" and select it.
4.  Enter your ista Calista portal **email** and **password**.
5.  Select the **Consumption Start Date**: This is the date from which the integration will attempt to import historical data (must be at least 1 month in the past, default is 1 year ago). *Note: ista often only provides data for the last 1-2 years.*
6.  Click **Submit**.

The integration will connect to your account, retrieve initial data, and create sensors for your meters. This initial sync might take a few minutes depending on the amount of historical data.

## Options

You can configure the update interval after installation:

1.  Go to **Settings** -> **Devices & Services**.
2.  Find the Ista Calista integration and click **Configure**.
3.  Adjust the **Update Interval (hours)** (default is 24 hours, minimum is 1 hour).
4.  Click **Submit**.

## Sensors

The integration creates the following sensors for each detected meter device:

* **Heating**: Total heating consumption (Unit depends on meter, often kWh or MWh).
* **Hot Water**: Total hot water consumption (Typically m³).
* **Water**: Total cold water consumption (Typically m³).
* **Last Measured Date**: Timestamp of the last reading received from the portal.

These sensors support Long-Term Statistics.

## Troubleshooting

* **Authentication Failed**: Double-check your email and password. If the issue persists, try logging into the ista Calista portal directly to ensure your credentials are correct.
* **Cannot Connect**: Verify your Home Assistant instance has internet access. The ista portal might be temporarily unavailable.
* **Missing Data/Sensors**: Ensure the "Consumption Start Date" is set correctly during setup. Check the Home Assistant logs (`home-assistant.log`) for errors related to `ista_calista` or `pycalista_ista`.

If you encounter issues, please [open an issue](https://github.com/YOUR_USERNAME/YOUR_REPOSITORY/issues) on GitHub.

## Contributing

Contributions are welcome! Please refer to the contribution guidelines (if any) in the repository.

## Disclaimer

This integration is not affiliated with, authorized, maintained, sponsored, or endorsed by ista International GmbH or any of its affiliates or subsidiaries. Use at your own risk.
