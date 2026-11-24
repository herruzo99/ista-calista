# Agent guide: Home Assistant integration `ista_calista`

Audit date: 2026-11-24. Audited local revision: `058ed9d`.
This guide describes the code as read. The audit did not fix production defects.

Read this guide before changing the integration. Read `../pycalista-ista/AGENTS.md` for the library it consumes. The integration and library release independently.

## 1. Safety rules

1. Do not put real account exports, passwords, cookies, invoice PDFs, serial numbers, or locations in tests, logs, fixtures, or commits.
2. Do not enable library DEBUG until `pycalista-ista` masks request data. Current DEBUG output includes the login password and session cookies.
3. Never close a session that Home Assistant owns. Since 0.10.0 the integration
   does not inject the shared session: runtime entries and config-flow
   validations create their own session and close it themselves, because
   library `close()` does not close an injected session.
4. Preserve UTC/date distinctions. Radio `Reading.date` is UTC midnight; billed/invoice fields are `date`; HA timestamp sensors localize date-only values.
5. Keep dynamic entity unique IDs stable. Registry duplicates can silently drop entities, especially for a second account.
6. Preserve old and new billed-consumption XLS headers in the library. Issue `herruzo99/ista-calista#4` was caused by the portal rename.
7. Run the full suite and Ruff before proposing a push. Current baseline: 68 tests pass and Ruff passes.
8. Do not claim long-term statistics work from unit tests alone. All current statistics tests mock the recorder boundary.
9. Do not push, tag, publish, or run a release workflow unless the owner explicitly asks.

## 2. What this integration is

`ista_calista` is a config-entry-only Home Assistant custom integration for the Ista Calista portal. It polls one account, exposes meter and billing entities, imports external long-term statistics, and downloads invoice PDFs.

Current manifest:

- Integration version: `0.10.0`
- Library requirement: `pycalista-ista~=0.9.4` (needs `account_id`, `PortalAccount`,
  `list_accounts` and `select_account`; 0.9.3 and older do not have them)
- HACS minimum Home Assistant: `2026.3.0`
- Quality scale declared: `gold` (no supporting `quality_scale.yaml` exists)
- IoT class: `cloud_polling`
- Integration type: `hub`
- Loads after `recorder`
- Platforms: `sensor`, `binary_sensor`, `button`

There is no YAML setup. Config-flow version is 2. `async_migrate_entry` in
`__init__.py` moves a version 1 entry to version 2 offline; the portal property
is resolved during setup, where a login is available. See section 18.

## 3. Architecture

```text
Home Assistant config entry
  └── async_setup_entry
        ├── private session: async_create_clientsession(hass, timeout=30 s)
        ├── PyCalistaIsta(email, password, private session, account_id=...)
        ├── login()
        ├── IstaCoordinator
        │     └── first refresh: 4 concurrent library calls
        ├── forward sensor / binary_sensor / button platforms
        ├── register download_invoice and get_invoices services
        └── update listener -> reload entry

sensor platform
  ├── coordinator listener -> dynamically add entities
  ├── meter sensors -> external recorder statistics
  ├── derived average / seasonal sensors
  ├── billed-reading sensors
  └── account / invoice / bill sensors

binary_sensor -> coordinator.last_update_success
button        -> debounced coordinator refresh
```

Coordinator data is a TypedDict:

```python
{
    "devices": dict[str, Device],
    "billed_readings": list[BilledReading],
    "invoices": list[Invoice],
}
```

The coordinator is stored in both `entry.runtime_data` and `hass.data[DOMAIN][entry.entry_id]`. Services iterate the second copy. Keep both copies consistent.

## 4. File map

| Path | Responsibility |
|---|---|
| `custom_components/ista_calista/__init__.py` | Setup, unload, removal, statistics cleanup, services |
| `custom_components/ista_calista/coordinator.py` | Polling, merge, invoice reconciliation, error policy |
| `custom_components/ista_calista/config_flow.py` | User, reconfigure, reauth, options flows |
| `custom_components/ista_calista/sensor.py` | Entity descriptions, dynamic creation, all sensor classes, LTS import |
| `custom_components/ista_calista/binary_sensor.py` | Account connectivity entity |
| `custom_components/ista_calista/button.py` | Manual refresh button |
| `custom_components/ista_calista/diagnostics.py` | Redacted diagnostic payload |
| `custom_components/ista_calista/const.py` | Domain, platforms, defaults, configuration keys, event |
| `custom_components/ista_calista/manifest.json` | HA metadata and library requirement |
| `custom_components/ista_calista/strings.json` | English source strings |
| `custom_components/ista_calista/translations/es.json` | Shipped Spanish translations |
| `custom_components/ista_calista/icons.json` | Entity icon overrides |
| `custom_components/ista_calista/services.yaml` | Service documentation |
| `custom_components/ista_calista/brand/` | HACS brand images |
| `tests/conftest.py` | Mock library and HA fixtures |
| `tests/test_init.py` | Setup, unload, removal, statistic cleanup |
| `tests/test_config_flow.py` | User, reconfigure, reauth |
| `tests/test_options_flow.py` | Options and reload |
| `tests/test_coordinator.py` | Fetch and merge policy |
| `tests/test_sensor.py` | Entity creation and basic state |
| `tests/test_sensor_statistics.py` | LTS calculations with recorder mocked |
| `tests/test_services.py` | Invoice listing/download service |
| `tests/test_diagnostics.py` | Diagnostic payload and password redaction |
| `tests/test_entry_lifecycle.py` | Reload state |

## 5. Setup and unload lifecycle

### Setup

1. `async_setup` initializes `hass.data[DOMAIN]` and registers the services.
2. `async_setup_entry` creates a private client session for this entry.
3. It constructs `PyCalistaIsta` and applies the configured log level globally to the library and integration loggers.
4. `await ista.login()` maps:
   - `IstaLoginError` → `ConfigEntryAuthFailed`
   - connection/API/other exceptions → `ConfigEntryNotReady`
5. It creates the coordinator and stores it in runtime data and `hass.data`.
6. `async_config_entry_first_refresh()` must succeed before platforms load. Failure becomes `ConfigEntryNotReady`.
7. Sensor, binary sensor, and button platforms are forwarded.
8. The two services are registered once, in `async_setup`, not per entry.
   Setup also calls the idempotent registration helper as a safety net.
9. An update listener reloads the entry when options change.

The log level is process-wide and is not restored on unload. Removing the integration does not guarantee DEBUG is off.

### Unload

1. Unload all platforms.
2. Call `ista.close()`, then `detach()` the private session of this entry. A
   session that Home Assistant owns is never touched.
3. Remove the coordinator from `hass.data`.

Services are registered once for the domain and stay registered after all
entries unload. They hold no entry closure: each call reads
`hass.data[DOMAIN]`, so an unloaded entry is simply not found.

### Removal

Before Home Assistant clears the device registry, the integration maps each registered meter model to a statistic ID and calls `recorder.async_clear_statistics`:

```text
Cold Water Meter  -> water
Hot Water Meter   -> hot_water
Heating Meter     -> heating
ista_calista:<serial>_<key>
```

Missing recorder, model, identifier, or unmapped type is logged and skipped. Manual deletion of API-derived devices is blocked.

## 6. Configuration flows

### Initial setup

Fields: email, password, consumption offset date, heating season start.

- Offset default: today minus one year.
- Offset newer than one month ago is rejected to limit the first download.
- Validation performs a real portal login and reads the properties of the
  account (`list_accounts`).
- One property: the entry is created without a second form.
- Several properties: the `select_account` step shows a `SelectSelector` with
  the property IDs as values and the labels as options.
- Unique ID is `<lowercase email>:<account_id>`.
- The title is `<email> — <label>`, or the email when no label is known.
- A duplicate `email:account_id` aborts (`already_configured`). A legacy entry
  of the same email (no property yet) also aborts, because it may become any
  property of that email.
- The account ID and the label are never logged.
- Password is included in `suggested_values` when an error form is shown again.

### Reconfigure

Same fields. Password is not suggested and must be retyped. Validation uses the
account ID of the entry, so the entry keeps its property. A legacy entry of an
account with several properties gets the `select_account` step here. Email or
property changes check conflicts against the other entries. Success updates the
unique ID, the title, the data, then reloads.

Important: reconfigure changes `data`, but `season_start` in `options` takes precedence. Once options contain a season start, reconfigure cannot change the effective season.

### Reauth

Password-only form using the stored email. The client is built with the
`account_id` of the entry, so reauthentication keeps the property. Success
updates the password and reloads.

### Options

- Update interval: 1–168 hours, default 24.
- Log level: standard logging names, default INFO.
- Season start: date, default September 1 of the current year if unset.

Submitting options stores all three and triggers reload. The coordinator reads the interval only in its constructor, so the reload is required.

## 7. Coordinator behavior

### Fetch window

- Initial fetch: configured offset through today.
- Later fetches: today minus 30 days through today.
- “Initial” means no current data **or no current devices**. An account with zero devices repeats the full historical fetch every cycle.

### Concurrent calls

```python
asyncio.gather(
    get_devices_history(start, end),
    get_billed_consumption(),
    get_invoices(),
    get_invoice_xls(),
    return_exceptions=True,
)
```

Device history is the only fatal source:

- login error → reauthentication required
- connection/API error → update failed
- unexpected error → update failed

Billed and invoice errors are warnings and become empty lists for that cycle. This is why a portal parser regression can silently remove billing state instead of failing the entry.

There is no overall refresh timeout. Library requests have their own timeout and retries, and one refresh performs several requests.

### Device merge

- The API response decides which devices exist.
- Existing and new readings merge by date; new values replace old values on the same date.
- Histories are sorted ascending.
- Devices absent from the response are dropped from coordinator data.
- Existing entities are not removed; they become unavailable.

### Invoice merge

XLS invoices are inserted first. HTML invoices then add `invoice_id` to an exact key match:

```text
(invoice_number, invoice_date, device_type, amount)
```

If no exact match exists and HTML `invoice_number is None`, the code falls back to matching date, type, and an amount difference below 0.01.

This fallback performs arithmetic on optional amounts. If either amount is `None`, it raises and fails the entire update. Current parsers can produce `amount=None`.

## 8. Entity inventory

### Meter device entities

One device per serial in the HA device registry. Model determines the meter key and unit.

| Unique ID suffix | Entity | Unit / class | Default |
|---|---|---|---|
| `heating` / `hot_water` / `water` | Meter total | kWh / m³, TOTAL_INCREASING | Enabled |
| `last_reading_date` | Last reading timestamp | TIMESTAMP, DIAGNOSTIC | Disabled |
| `average_daily_consumption` | 30-day daily average | kWh / m³, MEASUREMENT | Enabled |
| `seasonal_consumption` | Current heating-season use | kWh / m³ | Enabled |
| `billed_reading` | Latest billed consumption | MEASUREMENT | Enabled |
| `<meter>_lts_last_import` | Last external statistics import | TIMESTAMP, DIAGNOSTIC | Disabled |

Meter availability requires coordinator success and the serial still in current data.

Average daily consumption uses the last 30 days of history, with a last-two-reading fallback. It returns `None` for insufficient data, zero timespan, or negative use.

Seasonal consumption uses last minus first reading inside the season. Its `seasons` attribute is rebuilt from in-memory history, so older seasons disappear after a restart that does not download them.

### Account entities

Account device identifiers use `(DOMAIN, entry.entry_id)`.

| Unique ID | Entity |
|---|---|
| `<entry.unique_id>_latest_invoice_amount` | First invoice's amount, not an explicit maximum |
| `<entry.unique_id>_last_billed_date` | Newest billed date |
| `<entry.unique_id>_invoice_<type>` | Newest invoice amount per device type |
| `<entry.unique_id>_connection_status` | Binary connectivity sensor |
| `<entry.unique_id>_refresh` | Refresh button |
| `bill_name_<type>` | Newest HTML invoice ID per type |
| `bill_<number>_<type>` | Amount for a numbered invoice |
| `billed_date_<type>` | Newest billed date per type |

`last_billed_date` shares an availability rule that requires a nonempty invoice list. It becomes unavailable even when billed readings exist.

Per-type bill and billed-date unique IDs omit the account namespace. A second account with the same types loses those entities to registry duplicate warnings.

### Dynamic creation

The sensor platform registers a coordinator listener. On each update it adds entities whose unique IDs are not in local tracked sets. Entities are never removed when source data disappears. Tracked sets reset on platform reload, while the entity registry provides cross-reload identity.

An invoice with a number and `device_type=None` reaches `IstaBillSensor` and calls `.lower()` on `None`. This raises during sensor platform setup and prevents all sensors from loading.

## 9. Long-term statistics

Each meter sensor imports external statistics on add and after coordinator updates.

1. Build `ista_calista:<serial>_<meter_key>`, replacing `-` with `_`.
2. Read the last statistics row.
3. Select readings newer than its end timestamp.
4. Seed the previous state from the reading before the batch.
5. Accumulate positive deltas into `running_sum`.
6. On a negative delta, add the new meter value to the sum and move `last_reset`.
7. Call `async_add_external_statistics`.
8. Fire `LTS_UPDATED_EVENT` with the statistic ID.

The first meter reading contributes zero to the sum. Subsequent deltas accumulate. This differs from the meter's absolute `TOTAL_INCREASING` state.

A per-entity lock prevents overlapping imports. Tasks are fire-and-forget, unnamed, and have no failure callback.

### Critical compatibility finding

The code passes `unit_class` to `StatisticMetaData` (`sensor.py:744-752`). The pinned test environment is Home Assistant **2025.7.4**, whose `StatisticMetaData` does not accept that key. This was checked directly:

```text
HA: 2025.7.4
unit_class accepted: False
```

A real recorder import on that version raises `TypeError`. All six statistics tests patch `async_add_external_statistics`, so they do not detect it. The HACS manifest requires HA 2026.3.0; whether that version accepts the key was not verified here.

Other risks:

- Statistic IDs only replace hyphens. HA permits lowercase letters, digits, and underscores. Uppercase, dots, accents, or spaces can invalidate the ID.
- Date-only radio readings are UTC midnight, satisfying the hour-aligned timestamp requirement by current library behavior.
- Meter entities also use `state_class=TOTAL_INCREASING`, so HA can keep entity statistics alongside the external `ista_calista:*` series.

## 10. Services and button

### `ista_calista.download_invoice`

Input: required `invoice_id` string. Response-only service.

- Matches the invoice ID in every coordinator, collapses the matches to one
  row per entry (a coordinator can hold the same ID twice), then applies the
  optional selectors.
- `invoice_id` is required. `entry_id` (preferred) or `account_id` select the
  property. With several loaded properties and no selector the call fails with
  `ServiceValidationError` that lists the safe `entry_id` values: this code
  never picks the first match.
- Downloads through the client of the selected entry only.
- Writes to `<config>/www/ista_<device_type>_<YYYYMMDD>.pdf`. The device type
  is slugified with `homeassistant.util.slugify(..., separator="_")`, an empty
  result falls back to `invoice`, and the final name is rejected if it is not
  its own `basename`.
- If two loaded properties hold an invoice with the same device type and date,
  a short hash of the entry ID is appended, so the files do not overwrite each
  other. One matching property keeps the historical name.
- Returns success, filename, path, `entry_id`, `account_id`, `account_label`
  and `email`.

Remaining risks: `os.path.exists` still runs in the event loop; services stay
registered after unload; the returned path is not a `/local/...` URL.

### `ista_calista.get_invoices`

No input. Returns invoice dictionaries sorted by date descending. Each invoice
carries `entry_id`, `account_id`, `account_label` and `email`. Rows are
deduplicated by entry and `invoice_id` when present, otherwise by entry and
number/date/type/amount, so the same opaque ID on two properties gives two rows. Registration uses `supports_response=True` rather than `SupportsResponse.ONLY`.

### Refresh button

Calls `coordinator.async_request_refresh()`. The coordinator debouncer collapses near-simultaneous requests.

### Connection binary sensor

Diagnostic connectivity entity. `is_on` equals `coordinator.last_update_success`.

## 11. Translations, diagnostics, and assets

### Translations

The repository ships `strings.json` and `translations/es.json`, but no `translations/en.json`.

In an English test environment, entity names fell back to device class or `None`, producing IDs such as `sensor.living_room_none`. Config/options labels and translated exceptions have the same dependency. An English probe verified this behavior on HA 2025.7.4; newer HA behavior was not tested.

Spanish drift includes missing season fields, removed old fields, and a billed-reading name that loses its `{location}` placeholder. Several entity keys have no icon override.

### Diagnostics

Only password is redacted. Email, entry title, and device locations remain. Serials are SHA-256 truncated to eight characters. `coordinator_status.last_update` is the newest reading date, not the last successful refresh time. Billed readings, invoices, and entity counts are absent.

The module docstring incorrectly says “ista EcoTrend.”

### Assets

Icons are 256/512 squares. Logos are 291×128 and 582×256, not the square shape in HA brand guidance. Whether current hassfest rejects them was not run. License file is named `LICENCE`.

## 12. Development and verification

Run from the repository root:

```bash
nix develop --command pytest
nix develop --command pytest --no-cov -o addopts='' -q
nix develop --command pytest tests/test_sensor_statistics.py
nix develop --command ruff check .
```

Verified on 2026-11-24 at `058ed9d`:

- Tests: **68 passed**.
- Coverage with branch measurement: about **91.09%**.
- Ruff: **passes**.
- Nix environment: Home Assistant **2025.7.4**, Python **3.13.5**.
- Imported library: sibling `../pycalista-ista`, version **0.9.3**.

### Local library shadowing

`flake.nix` pins a Nix-built `pycalista-ista` 0.9.2, but `shellHook` prepends `../pycalista-ista` to `PYTHONPATH`. Local tests therefore use the sibling 0.9.3 work tree. CI without that sibling uses 0.9.2.

This matters: 0.9.3 contains the billed-header fix from issue #4. Local tests and CI do not currently exercise the same library parser version.

### Test map and gaps

- Setup/unload/removal: good exception and cleanup branch coverage.
- Config/reauth/reconfigure/options: covered, but not effective season precedence.
- Coordinator: fetch and merge covered; `amount=None` fallback is not.
- Statistics: calculations covered with recorder calls mocked; no real statistics write.
- Average and seasonal sensors: largely untested.
- Several invoice/bill/date/LTS-event entities: largely untested.
- Button behavior, binary sensor behavior, service cleanup, second account, and English translations: untested.
- No test uses the live portal; `PyCalistaIsta` is an `AsyncMock`.

## 13. Packaging, CI, HACS, and release

- `hacs.json`: `zip_release=true`, filename `ista_calista.zip`.
- Release workflow runs on `v*` tags or manual dispatch. It does not run tests.
- Tests workflow runs on `main` pushes/PRs. Validation workflow also runs nightly and on manual dispatch.
- A tag push can therefore release code that did not pass the main-branch test workflow.
- Release ZIP contains `custom_components/ista_calista/` and is validated before upload.
- GitHub releases `v0.9.2` and older currently have no ZIP assets. HACS asset downloads remain broken until the workflow creates one.
- Codecov upload is configured to fail when its token is absent.
- Manifest minimum HA is 2026.3.0, but tests run on 2025.7.4.
- `pyproject.toml` requires Python >=3.14 while the shell runs 3.13.5.
- Tracked `ha_ista_calista.egg-info/` is stale: version 0.1.5, library ~=0.6.0, Python >=3.10.
- `mypy strict` is configured but not run in CI.

Local Git state at audit:

- `origin/main`: `3802972`
- `gitea/main`: `8739fb8`
- Local `main`: `058ed9d`, two commits ahead of origin
- Working tree was clean before this guide was added

## 14. Known defects and risks

Labels: **V** = source-read or reproduced locally; **I** = inferred; **U** = version/live-portal dependent.

| ID | Severity | Status | Finding |
|---|---|---|---|
| B1 | High | V/U | External statistics pass unsupported `unit_class` on HA 2025.7.4; support in declared HA 2026.3.0 unverified. |
| B2 | High | I | Non-slug serials can create invalid statistic IDs. |
| B3 | High | V | Fixed in 0.10.0 (optional `device_type` guarded). Invoice with number and `device_type=None` crashes sensor setup. Reachability depends on upstream data. |
| B4 | High | V | Fixed in 0.10.0 (amounts compared only when both are numeric). Invoice fallback subtracts optional amounts; `None` fails the whole update. |
| B5 | High | V/I | Fixed in 0.10.0 (`translations/en.json` added). No English translations; English entity/form names fall back on tested HA 2025.7.4. |
| B6 | Medium | V | Reconfigure cannot override season start stored in options. |
| B7 | Medium | V | Fixed in 0.10.0 (account unique IDs carry the property). Account-level bill/date unique IDs collide across entries. |
| B8 | Medium | V | Fixed in 0.10.0 (services register once in `async_setup`). Services register per entry and are never removed; closure/client account can mismatch. |
| B9 | Medium | V | Partly fixed in 0.10.0: cross-property file collisions, device-type sanitization and client ownership are fixed. Still open: `os.path.exists` runs in the event loop and the returned path is not a `/local/` URL. Original finding: invoice download blocks for path checks/mkdir; filename collisions and weak sanitization. |
| B10 | Medium | V | `last_billed_date` is unavailable when invoices are empty but billed readings exist. |
| B11 | Medium | V/I | Seasonal attributes change after restart as old history leaves the fetched window. |
| B12 | Low | V | Fixed in 0.10.0 (bill entity resolves by invoice ID first). Bill entity resolves by invoice number only and ignores device type. |
| B13 | Low | I | Missing offset key has no migration/fallback and can cause permanent setup retry. |
| B14 | Low | V | Fixed 30-day incremental window misses older late readings; zero devices trigger full fetch every time. |
| B15 | Low | V | Transient billing/invoice errors replace previous lists with empty lists. |
| B16 | Low | V | Login errors from non-fatal calls do not trigger entry reauthentication. |
| B17 | Low | V | Global library/integration log levels are never restored. |
| B18 | Low | V | Statistics tasks are unnamed and unobserved. |
| B19 | Low | V | Spanish strings, icons, and service metadata drift. |
| B20 | Low | V | Partly fixed in 0.10.0: the property ID and label are redacted, the ID in `unique_id` is hashed and the label in the title is replaced. Still open: the email and the device locations remain in diagnostics, and the last reading is still labelled as the last update. |
| B21 | Low | V/U | Gold quality scale is declared without its rules file or supporting evidence. |
| B22 | Low | V | Python requirement, HA test version, coverage comment, and type-check configuration disagree. |
| B23 | Low | V | Release workflow bypasses tests; tracked egg-info is stale. |
| B24 | Low | V | CI depends on Codecov token and tests an older HA than the manifest minimum. |
| B25 | Cosmetic | V/U | Non-square logos and `LICENCE` filename may conflict with tooling/guidance. |
| B26 | Low | V | Password is fed back into a failed config form; email is logged. |
| B27 | Low | V | README entity table and binary-sensor wording are outdated. |
| B28 | Low | I | Entity and external statistics create parallel meter series. |

## 15. Cross-repository failure example: issue #4

1. The portal renamed `lectura anterior` and `lectura actual`.
2. `pycalista-ista` 0.9.2 raised `IstaParserError` in billed consumption.
3. The coordinator caught it as a non-fatal billing exception.
4. It stored an empty billed-reading list.
5. Billed sensors stopped updating or became unavailable; meter polling continued.
6. Local library revision `ff3458e` added aliases and `a62c3fe` released version metadata as 0.9.3.

Do not “fix” this only in the integration. The schema belongs to the library parser. Keep both names accepted there and add an integration test if changing the coordinator's stale-data policy.

## 16. Safe change checklist

1. Identify the layer: portal contract, library, coordinator, entity, recorder, service, translation, or release.
2. Add a failing test at the layer where the defect exists.
3. Keep injected HA sessions open and preserve cookie/session ownership.
4. Keep entity unique IDs stable and account-scoped where data is account-specific.
5. Treat `Invoice` and numeric fields as optional until proven otherwise.
6. Do not let one malformed invoice prevent unrelated meter entities from loading.
7. Test statistics through the real recorder boundary when changing metadata or IDs.
8. Add English translations when changing user-facing keys; update Spanish at the same time.
9. Run all 68 tests and Ruff. State explicitly if a real HA runtime path was not tested.
10. Check sibling library behavior and version when changing parser-related expectations.
11. Do not push, tag, publish, or dispatch release automation without explicit owner approval.

## 17. Limits of this audit

Every production Python file, JSON/YAML asset, packaging/config/workflow file, README/INFO, and all 12 test files were read. Both full suites and local probes were run. No real Ista account was used. Live portal shapes, real serial/type values, current GitHub/Gitea CI, HACS validation, hassfest, and HA 2026.3 statistics behavior were not verified. See `../ista-calista-audit.md` for the complete evidence inventory and detailed probes.





## 18. Experimental multi-property support (0.10.0)

Status: **synthetic two-property tested; live single-property verified only.**
The live portal account of this project holds one property. The isolation
tests use two synthetic properties, so live multi-property behaviour is
unverified.

### Entry identity

- Each entry stores `account_id` (opaque portal value) and `account_label`
  (user-facing; it may be an address) in `entry.data`.
- Unique ID: `<lowercase email>:<account_id>`.
- Title: `<email> — <label>`.
- Account device identifiers stay `(DOMAIN, entry.entry_id)`, so they are
  unique per property. The account device name is `Ista Account <label>`, or
  `Ista Account <email>` without a label.
- The account ID and the label are never written to the log. Diagnostics
  redact the password, the account ID and the label, replace the account ID in
  the entry `unique_id` by a short hash and replace the label in the title.

### Legacy version 1 entries

1. `async_migrate_entry` bumps the version to 2. It makes no network call.
2. Setup builds the client without `account_id`, logs in, then calls
   `list_accounts`.
3. Exactly one property: `account_id` and `account_label` are stored, the
   unique ID becomes `<email>:<account_id>`, the title is updated. No user
   action.
4. Several properties: `ConfigEntryError` with a "reconfigure required" text.
   The entry is not loaded and no property is chosen silently.
5. No property: `ConfigEntryError`.

### Session lifecycle

- Setup creates one private session per entry:
  `async_create_clientsession(hass, timeout=SESSION_TIMEOUT)`, where
  `SESSION_TIMEOUT` is 30 s (`const.py`). `async_get_clientsession` is not used
  in setup.
- Each config-flow validation (user, reconfigure, reauth) creates its own
  private session and detaches it in `finally`. Two simultaneous flows of one
  email therefore do not share a cookie jar.
- The library closes only the sessions that it created itself. The integration
  calls `session.detach()` in `async_unload_entry`, in the failure paths of
  setup and in the `finally` of each config-flow validation. Do **not** call
  `await session.close()`: on a session of `async_create_clientsession`
  (`const.WARN_CLOSE_MSG`) `close` is replaced by a usage reporter that does not
  close anything. `detach()` is idempotent, so the detach that Home Assistant
  registers on entry unload is safe.
- A failed setup detaches the session and removes the coordinator from
  `hass.data[DOMAIN]`.

### Unique ID namespaces

- Account level (namespace = `entry.unique_id`): `latest_invoice_amount`,
  `last_billed_date`, `invoice_*`, `billed_date_*`, `bill_name_*`, `bill_*`,
  `connection_status`, `refresh`.
- Meter level: `<serial>_<key>`, `<serial>_billed_reading`,
  `<serial>_average_daily_consumption`, `<serial>_seasonal_consumption`,
  `<serial>_<key>_lts_last_import`. These stay serial based so existing
  long-term statistics keep their `ista_calista:<serial>_<key>` IDs.
- **Limitation:** two properties that report the same meter serial would
  collide on the meter unique IDs and the statistic IDs. Splitting the
  namespace per property would rename the statistics of existing users, so it
  was not done. No live portal showed this collision.

### Services

`download_invoice` and `get_invoices` are registered once, in `async_setup`.
They iterate `hass.data[DOMAIN]` and use the coordinator that owns the invoice
ID, so account A never downloads through the client of account B.
`get_invoices` adds `entry_id`, `account_id`, `account_label` and `email` to
every invoice, deduplicates by `invoice_id` when present (otherwise by the
pre-0.10.0 key) and sorts newest first, with undated invoices last.

### Invoice data

- The library follows all pages of the HTML invoice list (15 rows per page) and
  returns the merged list. The coordinator keeps the XLS history and adds the
  HTML invoice IDs.
- A row with an ID but no invoice number still becomes a bill entity.
- Merged invoices are sorted by date, newest first, `None` last.
- Each detailed (HTML) invoice claims at most one history (XLS) row, so two
  rows with the same date, type and amount keep their distinct IDs. Two
  identical history rows are one invoice. A repeated detailed row with the same
  invoice ID is ignored.
- The download file name is `ista_<device_type>_<date>.pdf`. If two loaded
  properties hold an invoice with the same device type and date, a short token
  from the entry ID is appended, so one property cannot overwrite the file of
  the other. A single matching property keeps the historical name.

### Live validation caveat

The two-property behaviour, the private cookie jars, the property selection and
the per-property invoice access were verified with synthetic fixtures only. A
live run against a two-property account is still required.
