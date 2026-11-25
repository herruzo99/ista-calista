# Live Ista Calista portal: feature audit and service coverage

Research date: **2026-11-24**. Portal build observed in page headers: **v.2.110.4**.

This document compares the live customer portal with `pycalista-ista` and the Home Assistant integration `ista_calista`. It records observed features, data contracts, coverage gaps, and implementation priorities.

No credentials or personal account values are included. Raw authenticated pages and downloads are not part of the repository.

## Implementation status (2026-11-24)

This document began as a live feature audit. Two requested features were then implemented:

- **Complete invoice access — implemented in `pycalista-ista` 0.10.0 and `ista-calista` 0.10.0.** The library follows every invoice-list page, deduplicates opaque PDF IDs, stops on repeated URLs, and caps at 50 pages. Home Assistant keeps the full merged history and downloads through the property that owns the ID. Live verification returned 63 HTML invoices and 63 unique PDF IDs, exactly matching the 63-row XLS history.
- **Multi-property support — implemented as EXPERIMENTAL.** One config entry represents one portal property. Entries use private cookie jars and property-scoped account identities. Synthetic two-property tests pass. Only one real property was available for live validation. A multi-property selection without an explicit selected marker fails closed rather than guessing.
- **Credential-safe DEBUG logging — implemented in 0.10.0.** Passwords, cookie values, one-time tokens, and property selector pages are redacted.

The matrix below shows the post-implementation state. Rich invoice-PDF parsing, CSV/PDF table exports, charts, account mutations, manual readings, simulations, incidents, and portal alerts remain unimplemented.

## 1. Scope and method

### Evidence used

1. Authenticated, read-only inspection of the live portal.
2. GET requests for feature pages, exports, chart pages, and one invoice PDF.
3. Live calls through the local `pycalista-ista` work tree. The original audit used 0.9.3; final implementation checks used 0.10.0.
4. Direct parsing of live CSV, XLS, and PDF responses.
5. The official customer manual linked by the portal:
   `https://www.ista.com/fileadmin/media_ista/spain_es/Documents/Manuales/Manual_Calista_Abonados.pdf`
   (20 pages, document dated 2025-09-30).

### Safety boundary

- Pages and exports were read.
- Forms were inspected but **not submitted**.
- No reading was entered.
- No incident was sent.
- No alert or account setting was changed.
- No paperless-billing checkbox was toggled.
- No account linkage was removed.
- No payment or other financial action was attempted.
- No logout was requested, so the research did not invalidate an existing browser session.

### Confidence labels

- **Live verified**: observed in an authenticated page, response, export, or local library call.
- **Manual documented**: described by the official manual but not exercised live.
- **Code verified**: confirmed in the two repositories.
- **Inferred**: a likely implementation path or behavior that needs a safe follow-up test.

### Important limits

- One customer account was inspected. Feature visibility can differ by meter type, account linkage, and portal rollout.
- The portal's default dashboard returned an application error during research. Direct feature URLs worked.
- The public registration URL printed in the manual returned 404 during research. The public login site blocked automated inspection. Registration and password recovery are therefore manual-documented, not live verified.
- The official manual and current live UI differ in some alert features. The live UI is treated as current evidence; the difference is recorded in §8.7.
- Export contents and labels can vary between customers. The October 2026 billed-column incident shows that this variation is real.

## 2. Executive summary

### Covered well

The service already covers the three main data-heavy features:

1. **Radio readings**: daily meter history through XLS exports.
2. **Billed consumption**: historical billed readings and consumption through XLS exports.
3. **Invoices**: HTML invoice list, XLS history, and individual PDF download.

The Home Assistant integration turns those into meter sensors, derived consumption sensors, billed-reading sensors, invoice sensors, long-term statistics, diagnostics, a refresh button, and invoice services.

### Not implemented

The portal also provides:

- Manual meter-reading submission.
- Cost simulation (`¿Cuánto pagaré?`).
- Incident reporting.
- Email alerts for readings and consumption.
- Paperless/digital receipt settings.
- Account email, phone, and password changes.
- Linked-property unlinking.
- Multi-property account selection.
- Radio-history charts.
- Registration and password recovery.
- CSV and PDF table exports.
- Rich invoice-PDF data extraction.

### Most important discoveries

1. **CSV is not a full alternative to XLS.** Live radio CSV contains only meter metadata. Live billed CSV contains only serial, type, and date. Invoice CSV matches invoice XLS.
2. **PDF table exports differ by feature.** Radio PDF contains meter metadata only. Billed and invoice PDFs contain tabular history.
3. **The chart is a two-step web flow.** `generarGraficoOV` returns HTML; that page loads `generarGraficoIndividual`, which returns PNG.
4. **Invoice PDFs contain data absent from both HTML and XLS.** This includes invoice number, issue date, billing period, line items, VAT, totals, and community statistics.
5. **The portal paginates its HTML invoice list.** The first manual page inspection returned 15 rows while XLS contained 63. The 0.10.0 implementation now follows every page; live verification returned all 63 unique PDF IDs.
6. **The live billed XLS currently uses old column names.** HTML also used old labels in this account. Keep both old and new names supported because issue #4 affects other accounts/exports.
7. **Four raw billed rows were intentionally skipped.** They use `_` as the serial. The parser's 389 results from 393 raw rows are correct for device readings.
8. **The billed export contains incidence codes our label map does not explain.** `47C9` and `47A5` appeared live. The library names only `4700`, `47A4`, `47AA`, and `4741`.
9. **One live billed row had negative consumption.** The model accepts it. Consumers must not assume every billed delta is positive.
10. **The manual lists an invoice alert, but the live alert menu showed only three tabs.** Live tabs were readings, period consumption, and daily consumption.

## 3. Coverage matrix

Coverage meanings:

- **Full**: main live data/action is available through the service.
- **Partial**: useful data exists, but fields, formats, or behavior are missing.
- **Read-only only**: the service can retrieve related data but cannot perform the portal action.
- **None**: no service implementation.
- **External**: the portal links outside the authenticated service.

| Portal feature | Live status | `pycalista-ista` | Home Assistant integration | Coverage |
|---|---|---|---|---|
| Sign in | Live verified | Keycloak login and relogin | Setup and reauth flows | Full |
| Automatic session renewal | Code verified; live session worked | Host-based expiry detection and one retry | Coordinator error mapping | Partial |
| Registration | Manual documented; old URL 404 | None | None | None |
| Forgotten password | Manual documented | None | None | None |
| Logout | Link observed | `VirtualApi.logout` only | Not exposed | Partial |
| Dashboard/home | Live error observed | Not used | Not used | None |
| Property/account selector | Live verified | `list_accounts` / `select_account` (experimental) | One entry per property; private session | Experimental full |
| Switch linked property | Form/script observed | Verified `select_account` | Entry selection/reconfigure | Experimental full |
| Paperless receipts | Live verified | None | None | None |
| View account data | Live verified | Login uses email only | Stores email in config entry | Partial |
| Change email/phone/password | Live verified | None | Reauth updates HA-stored password only | None |
| Unlink a property | Live verified | None | None | None |
| Invoice list | Live verified | All HTML pages, deduplicated IDs | Full merged history and entities | Full for list/history |
| Invoice PDF download | Live verified | PDF bytes | Writes PDF to `config/www` | Full for download |
| Invoice PDF structured data | Live verified | Not parsed | Not exposed | None |
| Invoice XLS history | Live verified | Full XLS parse | Merged with HTML | Full |
| Invoice CSV | Live verified | None | None | None |
| Invoice PDF table export | Live verified | None | None | None |
| Manual reading form | Live verified | None | None | None |
| Submit manual reading | Form observed; not submitted | None | None | None |
| Billed consumption history | Live verified | Full XLS parse | Billed sensors | Full for XLS |
| Billed CSV | Live verified | None | None | None |
| Billed PDF table | Live verified | None | None | None |
| Billed type filter | Live verified | Always fetches all types | Shows per serial/type | Partial |
| Billed sort/pagination | Live verified | File order from XLS | Uses list order | Partial |
| Radio daily history | Live verified | Chunked XLS parse | Meter sensors/LTS | Full for XLS |
| Radio date filter | Live verified | Public start/end arguments | Offset and 30-day refresh window | Full |
| Radio chart | Live verified | None | HA history graph is separate | None |
| Radio CSV metadata | Live verified | None | Device metadata exists from XLS | Partial |
| Radio PDF metadata | Live verified | None | Device metadata exists from XLS | Partial |
| Cost simulation | Live verified | None | None | None |
| Simulation PDF | Manual documented; not generated | None | None | None |
| Incident form | Live verified | None | None | None |
| Submit incident | Form observed; not submitted | None | None | None |
| Reading-date email alert | Live verified | None | None | None |
| Period-consumption alert | Live verified | None | None | None |
| Daily-consumption alert | Live verified | None | None | None |
| Invoice-issued alert | Manual documented; absent from live tabs | None | None | Unclear |
| Blog | External link | None | None | External |
| User manual | External PDF | None | README links to project docs | External |
| Privacy/cookie pages | External links | None | None | External |
| Customer support | Live verified | None | None | External |

## 4. Portal information architecture

The authenticated menu exposes these primary destinations:

1. `Mis recibos`
2. `Dar mi lectura`
3. `Mis consumos`
4. `Mis lecturas Radio`
5. `¿Cuánto pagaré?`
6. `Reporte una incidencia`
7. `Blog` (external)
8. `Mis alertas`

Header actions:

- `Mi cuenta`
- `Salir`

Cross-page controls:

- Linked-property selector.
- `Volver` to the property finder.
- `Fincas` to the account/property search.
- Paperless-receipt checkbox.
- User manual link.
- Incident/support link.
- Privacy and cookie links.
- Advertising banner.

### Dashboard behavior

The default `GestionOficinaVirtual.do` page returned HTTP 200 with an application-error message. It still showed the authenticated header and support/manual links. The error body identified no account-specific technical cause beyond a generic application action.

This matters because the integration does not depend on that dashboard. Login is followed by a radio-metadata preload, and data calls use feature endpoints directly. A broken dashboard therefore did not prevent the service from reading data.

## 5. Feature-by-feature research

### 5.1 Authentication and session

**Live verified:** authenticated pages loaded after the library's Keycloak flow.

**Code verified:** `VirtualApi.login()` performs:

1. Authorization-form discovery.
2. Credential POST through Keycloak and portal redirects.
3. Radio-metadata preload.

`_send_request()` detects some expired sessions, clears portal cookies, logs in again, and retries once.

**Coverage:** Full for normal login; partial for expiry detection because it relies on host/page heuristics.

**Gaps and risks:**

- A second login page after the one allowed relogin can be accepted as HTTP 200.
- Shared Home Assistant sessions mean multiple entries share one cookie jar.
- Version 0.10.0 masks credentials, cookies, one-time tokens, export URLs, connection-error text, and property selector pages. Preserve its redaction tests before enabling DEBUG.
- Public logout exists in the library's lower layer but is not exposed by `PyCalistaIsta`.

### 5.2 Registration and password recovery

**Manual documented:**

- Registration uses customer/account number, reading date, and invoice amount from a bill.
- The user supplies email, password, repeated password, and accepts access conditions.
- Password minimum: 10 characters, uppercase, lowercase, number, and special character.
- Multiple properties can be linked under one login by registering each with the same email and password.
- Password recovery sends an email link and then accepts a new password with the same complexity rules.

**Live verification limit:** the manual's registration URL returned 404. The public login site returned 403 to the automated fetch. No registration or recovery action was attempted.

**Coverage:** None. These are intentionally outside Home Assistant's role.

**Product recommendation:** keep recovery in the official portal/browser. Do not automate account creation or password reset in the integration.

### 5.3 Multi-property accounts and property selection

**Live verified:** feature pages contain a property selector. Account pages list linked properties with columns for selection, account, address, digital receipt, and email in the raw page.

**Manual documented:** changing the selected property changes the data and documents shown in the menu. Digital-receipt selection affects all linked accounts.

**Code verified:** the integration creates one config entry per lowercase email and aborts duplicate emails. It does not pass a property identifier to `PyCalistaIsta`.

**Coverage:** Partial. A single linked property works. Multiple properties under one email are not selectable in the integration.

**Important design constraint:** adding a second entry with the same email is blocked by the config-flow unique ID. A future multi-property design needs a property/account identifier in the config entry, library constructor or session-selection method, entity namespace, and coordinator title.

Do not confuse this with two different portal accounts. Two different emails can be configured, but current entity unique IDs still collide for some account-level billing entities.

### 5.4 Paperless/digital receipts

**Live verified:** a checkbox appears on every authenticated feature page and on `Mi cuenta`. The browser script submits `envioDigitalizado` to `GestionOficinaVirtual.do`.

**Manual documented:** the user can enable or disable digital-only receipt delivery. The setting affects all linked accounts.

**Coverage:** None. The research did not toggle it.

**Possible future feature:** expose a read-only status sensor first. A write action should require explicit user confirmation because it changes paper delivery for every linked property.

### 5.5 `Mi cuenta`

**Live verified fields:**

- Email.
- Mobile phone.
- Current password.
- New password.
- Repeat new password.
- Digital-receipt checkbox.
- Linked-property table.
- `Guardar`, `Volver`, and `Eliminar` actions.

**Manual documented:** changing email affects all linked registrations. Selected linked properties can be removed from the login.

**Coverage:** None for portal changes. Home Assistant stores its own email/password so it can authenticate, but it does not update the portal account.

**Safety recommendation:** do not add account mutation services to the initial roadmap. They are high-impact, security-sensitive, and not needed for metering.

### 5.6 `Mis recibos`

#### Live behavior

- Paginated HTML table.
- Sortable columns: reading date, device type, amount, download.
- Individual PDF download per row.
- Excel history export.
- CSV export.
- PDF table export.
- Digital-receipt control and property selector.

#### Live evidence

- HTML first page: **15 invoices**, all with opaque PDF IDs.
- XLS history: **63 rows**, none with PDF IDs.
- Individual PDF download: valid PDF bytes.
- XLS columns: `Fecha lectura`, `Tipo equipo`, `Importe`.
- CSV and XLS had the same 63 rows and normalized cell text.
- PDF table export contained date, type, and amount.

#### Service coverage

`VirtualApi.get_invoices()` follows every HTML page and supplies PDF IDs. `get_invoice_xls()` reads full XLS history. `get_invoice_pdf(id)` downloads bytes. The coordinator merges XLS history with all HTML IDs. Live verification returned 63 HTML rows, 63 XLS rows, identical unique keys, and 63 merged IDs.

Home Assistant exposes invoice amounts, latest billed dates, bill-name/ID entities, invoice listing, and PDF download.

#### Gaps

1. Rich invoice-PDF fields are not parsed; the service keeps the original PDF bytes.
2. CSV and PDF table exports are unsupported.
3. Pagination has a 50-page safety cap; ambiguous paging stops rather than guessing.
2. The merge matches date/type/amount because HTML and XLS lack a shared invoice key.
3. `invoice_number` and billing periods are not parsed from HTML/XLS.
4. The PDF's rich content is discarded.
5. CSV and PDF table exports are unsupported.
6. `Invoice.amount` and `device_type` are optional in the model, but the coordinator's fallback arithmetic assumes amounts are numeric.
7. Bill entities are created only when `invoice_number` exists. Current HTML/XLS parsers never fill it, so those entities are effectively dormant for these feeds.
8. A downloaded file name based on type/date can overwrite another invoice on the same date.

#### Rich PDF fields observed

The individual invoice PDF contained:

- Customer/account and invoice identifiers.
- Invoice number.
- Invoice issue date.
- Billing period start/end and day count.
- Reading date.
- Delivery and reading addresses.
- `LECTURAS Y CONSUMOS` table: ID, type, previous reading, current reading, consumption, incidence.
- `LIQUIDACIÓN` table: ID, concept, consumption, amount, VAT.
- Tax base, tax rate, VAT amount.
- Total amount.
- Statement that ISTA reads/liquidates but does not collect payment.
- Community-period general expenses.
- Community consumption units and average.
- Unit-price calculation, blocks, and rates.
- Community comparison information.
- Duplicate-document marking.

None of these personal values are reproduced here.

**Coverage:** Partial overall; full for PDF download, partial for structured data.

### 5.7 `Dar mi lectura`

**Live verified:**

- Page title `Dar mi lectura`.
- Table columns: serial, meter, previous reading, `Mi lectura`.
- Two meter rows were available in the inspected account.
- Text input name: `miLectura`.
- Hidden meter and previous-reading values.
- `aceptar` submit action.
- Message: the next reading date will be scheduled shortly.

**Manual documented:** manual submission is needed for mechanically read meters, not radio meters. The previous reading helps detect entry mistakes. An annex explains direct-read and dial meters.

**Coverage:** None. The form was not submitted.

**Future implementation risk:** this is a write operation. It needs validation, duplicate-submission protection, idempotency, a confirmation step, and clear separation from radio-meter polling. Do not implement it as a side effect of refresh.

### 5.8 `Mis consumos`

#### Live behavior

- Paginated billed-reading history.
- Device-type filter: all, cold water, heating cost distributor, hot water.
- Sortable columns: serial, type, date, incidence, previous reading, current reading, consumption.
- Excel, CSV, and PDF exports.
- Linked-property and paperless controls.

#### Live export evidence

- XLS: **393 rows**, 10 columns.
- Parsed device readings: **389**.
- Skipped rows: **4**, all serial `_`.
- Raw date range included filler records from 2021; parsed readings ran from 2022-03-31 to 2026-10-30.
- Current XLS columns:
  `Nº serie`, `Tipo equipo`, `Ubicación`, `Id lectura`, `Fecha`, `Incidencia`, `Unidad Medida`, `Lectura anterior`, `Lectura actual`, `Consumo`.
- Current HTML labels also used `Lectura anterior` and `Lectura actual`.
- Numeric columns were integer-valued in this export.
- No empty numeric cells were observed in this account.
- 35 rows had no location.
- 260 rows had zero consumption.
- One row had negative consumption.
- Incidence counts included `4700`, `47AA`, `47A4`, `4741`, `47C9`, and `47A5`.
- CSV: **393 rows but only three columns**: serial, type, date.
- PDF: tabular billed history.

#### Service coverage

`ConsumptionParser` accepts old and new reading-column names, validates required columns, skips `_` rows, and returns `BilledReading` objects. Home Assistant shows latest billed consumption per serial, estimated status, incidence, previous reading, date, and per-type billed dates.

#### Gaps

1. CSV and PDF exports are not supported.
2. Portal filters are not exposed; the service fetches all types.
3. Portal sort/pagination controls are not reproduced.
4. `47C9` and `47A5` have no entry in `INCIDENCE_NAMES`.
5. The docstring says descending date order, but the parser returns file order.
6. Empty numeric cells can become `NaN`; not observed live here, but reproduced in offline tests.
7. Decimal-comma strings can drop rows; current live cells were numeric, but the risk remains for other exports.
8. Billed parsing runs on the event loop.

**Coverage:** Full for current XLS data; partial for formats and UI behavior.

### 5.9 `Mis lecturas Radio`

#### Live behavior

- Date-range form.
- Daily columns, newest first.
- Meter metadata: location, serial, type, unit.
- Per-meter chart link.
- Excel, CSV, and PDF exports.
- Linked-property and paperless controls.

**Manual documented:** daily radio readings are uploaded to the server once per week. The portal can show daily values after that upload.

#### Live export evidence

- Default visible table showed 10 daily columns.
- XLS contained **28 columns**: four metadata columns plus 24 daily dates.
- **11 devices**: nine heating, one cold water, one hot water.
- Local library request from 2024-01-01 through the research date returned **10,157 readings** across those devices.
- Earliest returned reading: 2024-03-20. Latest: 2026-11-17.
- No `None` values remained in the merged library history.
- XLS included missing daily cells before interpolation.
- CSV: **11 rows and only four metadata columns**. It omitted every daily reading.
- PDF: meter metadata only. It omitted every daily reading.
- XLS `Unidad Medida` values were `UN` for heating and `m3` for water.

#### Service coverage

`ExcelParser` handles `.xls` and `.xlsx`, parses daily headers and decimal-comma values, creates device subclasses, chunks long ranges, merges histories, and interpolates missing internal values.

Home Assistant exposes totals, reading dates, 30-day averages, seasonal consumption, and external long-term statistics.

#### Gaps

1. Portal charts are unsupported.
2. CSV/PDF radio exports cannot replace XLS because they contain no readings.
3. The service's interpolation is not the same as viewing the portal's raw daily table.
4. Portal data arrives weekly according to the manual, so a daily Home Assistant update does not imply new daily source data.
5. Long initial ranges are chunked into sequential requests.
6. A meter reset can crash `Device.last_consumption` in the current library.
7. Lowercase `nº serie` is normalized incorrectly in the radio parser; current live export uses `Nº Serie` and works.

**Coverage:** Full for XLS history; none for portal charts.

#### Chart flow

1. `generarGraficoOV` returns an HTML page titled `Mis lecturas`.
2. That page contains an image URL using `generarGraficoIndividual` with serial and date range.
3. The image endpoint returns `image/png` (22,863 bytes in the sample).

A future chart feature should use the image endpoint for portal fidelity or Home Assistant's own history graph for local visualization. They are separate data sources.

### 5.10 `¿Cuánto pagaré?`

**Live verified:**

- Table columns: serial, meter, previous reading, `Mi lectura`.
- Input name: `lecturaRadio`.
- Submit button: `Calcular`.
- Two meter rows in the inspected account.
- Export icons existed, but all three returned the same HTML error page when requested without a calculation.

**Manual documented:** the user enters a current meter reading to calculate consumption/cost between readings, for example at tenant change. The system generates a simulated PDF receipt. The simulation has no validity and does not register the reading for future billing.

**Coverage:** None. No calculation was submitted.

**Future implementation warning:** even though the manual says the reading is not stored, this endpoint has financial and write-like semantics. Treat it as an explicit user action, never as polling. Label results as estimates, not invoices.

### 5.11 `Reporte una incidencia`

**Live verified fields:**

- Contact name.
- Mobile phone.
- Incident type.
- Description.
- Linked-property selector.
- `aceptar` submit action.

**Live incident types:**

- `Otros`
- `Lectura`
- `Emisión de recibos`
- `Dispositivo/equipo`

**Live notice:** changes to the property holder or bank account must be handled through the community's legal representative, not this form.

**Coverage:** None. No incident was submitted.

**Future implementation warning:** a service that sends incidents needs user confirmation, rate limiting, audit logging, and protection against duplicate submissions. It should not be automated from sensor thresholds without explicit consent.

### 5.12 `Mis alertas`

#### Live tabs

1. `Lecturas`
2. `Consumo periodo`
3. `Consumo diario`

#### Reading alert

- Checkbox field `flgMailLectura`.
- Email notification setting.

#### Period-consumption alert

- Read-only habitual consumption.
- User threshold field `avisoPeriodo`.
- Notification checkbox `flgMailConsumoPeriodo`.
- Unit: **m³**.
- Live text: applies only to cold-water equipment.
- Description: warning when consumption exceeds the chosen amount in each consumption period.

#### Daily-consumption alert

- Read-only habitual daily consumption.
- User threshold `avisoDiario`.
- Notification checkbox `flgMailConsumoDiario`.
- Unit: **liters/day**.
- Live text: unavailable without a smart meter; a replacement quote can be requested.

#### Manual difference

The official manual also lists an **invoice-issued alert**. That tab/control was not present in the live menu inspected. It may have been removed, renamed, or hidden for this account. Treat it as uncertain, not as a confirmed current feature.

**Coverage:** None.

**Home Assistant alternative:** threshold automations can approximate these alerts locally, but they are not portal email alerts. Document the data source and latency: radio source data may arrive weekly.

### 5.13 Blog, manual, support, privacy, and cookies

These are external resources:

- Blog: `ista.com/es/empresa/mundo-ista`.
- Customer manual PDF.
- Privacy policy.
- Cookie policy.
- Support phone and incident link.
- Advertising link.

**Coverage:** External. They are not data APIs and should not be scraped into Home Assistant.

The manual is useful for feature semantics, but its registration link and alert list show that it can lag behind the live portal.

## 6. Live export contract

### 6.1 Format selector

Live table pages exposed three export links:

| Selector value | Response | Radio content | Billed content | Invoice content |
|---|---|---|---|---|
| `e=1` | UTF-8 CSV | Metadata only | Serial/type/date only | Full three-column history |
| `e=2` | `application/vnd.ms-excel` | Metadata + daily readings | Full 10-column history | Full three-column history |
| `e=5` | PDF | Metadata only | Tabular history | Tabular history |

The observed query key `6578706f7274` is hex text for `export`.

### 6.2 Encoding and delimiters

- CSV responses declared UTF-8.
- No UTF-8 BOM was observed in the three CSV samples.
- Comma was the field delimiter.
- Decimal commas appeared inside amount text, so a CSV parser must respect quoting.
- XLS responses were OLE2 BIFF files, not XLSX.
- Magic-byte engine detection is therefore correct for these live responses.

### 6.3 PDF behavior

- Radio PDF is not a reading export; it is a meter list.
- Billed PDF is a printable history.
- Invoice PDF is a printable history.
- Individual invoice PDF is a rich financial document.
- Cost-simulator export links returned HTML when no simulation existed.

### 6.4 Library format policy

The service should continue to use **XLS for data completeness**. CSV can be a future lightweight option only if its missing columns are acceptable. PDF should be used for documents, not as the primary parser input.

## 7. Live-to-model data mapping

### 7.1 Radio XLS → `Device` / `Reading`

| Live field | Model | Notes |
|---|---|---|
| `Ubicacion` | `Device.location` | Can be blank |
| `Nº serie` | `Device.serial_number` | String key |
| `Tipo` | Device subclass | Heating/cold/hot by substring |
| `Unidad Medida` | Not stored in `Reading` | Unit inferred from device class in HA |
| `dd/mm/yy` columns | `Reading.date` | UTC midnight |
| Cell value | `Reading.reading` | Decimal comma normalized; blanks interpolated/trimmed |

### 7.2 Billed XLS → `BilledReading`

| Live field | Model | Notes |
|---|---|---|
| `Nº serie` | `serial_number` | `_` rows skipped |
| `Tipo equipo` | `device_type` | Spanish label retained |
| `Ubicación` | `location` | Blank becomes empty string |
| `Id lectura` | `reading_id` | Integer |
| `Fecha` | `date` | Date only |
| `Incidencia` | `incidence` | Some codes lack names |
| `Unidad Medida` | `unit` | `UN` or `m3` observed |
| Previous/current/consumption | Float fields | `NaN` and comma-string risks remain |

### 7.3 Invoice HTML/XLS → `Invoice`

| Live field | Model | Notes |
|---|---|---|
| HTML `idRecibo` | `invoice_id` | Opaque PDF-download key |
| Reading date | `invoice_date` | Date only |
| Device type | `device_type` | Optional in model |
| Amount | `amount` | Optional in model |
| Invoice number | `invoice_number` | **Not present in HTML/XLS** |
| Billing period | `period_start/end` | **Not present in HTML/XLS** |

### 7.4 Invoice PDF → currently no structured model

The richest source is downloaded as bytes and saved. It is not parsed. Adding structured PDF extraction would be a separate, fragile feature. PDF layouts, fonts, duplicates, and language can change. Keep the original PDF as the authoritative document even if selected fields are extracted later.

## 8. Comparison with the official manual

| Manual statement | Live result |
|---|---|
| Eight menu features | Matches live menu |
| Multiple properties under one login | Selector and account table observed |
| Digital receipts affect all accounts | Confirmed by manual; setting not changed live |
| Account email/phone/password can change | Form observed |
| Linked properties can be removed | Delete action observed |
| Invoice PDF and Excel history | Both work |
| Excel invoice summary includes invoice number | Current live XLS has only date/type/amount; no invoice number |
| Manual reading for non-radio meters | Form observed with two rows |
| Billed history with Excel export | Works |
| Radio daily readings uploaded weekly | Manual statement; upload cadence not independently measured |
| Cost simulator creates non-valid PDF | Manual statement; no simulation submitted |
| Four incident categories | Live form showed four listed categories |
| Alerts: invoice, reading, period, daily | Live showed reading, period, daily only |
| Period alert in m³ | Live confirms m³ and cold-water-only note |
| Daily alert in liters | Live confirms liters and smart-meter requirement |
| Registration at printed URL | Printed URL returned 404 |
| Password complexity rules | Manual only; not tested |

The invoice-number discrepancy is important: the current live XLS does not match the manual's example description. Do not build logic that assumes an invoice number will appear there.

## 9. Service architecture against live features

### 9.1 What the library does well

- Uses the real Keycloak flow.
- Keeps authentication out of Home Assistant platform code.
- Supports caller-owned sessions.
- Finds export links in live HTML.
- Handles current OLE2 XLS files.
- Supports long radio-history ranges with chunking.
- Accepts both billed-reading header variants.
- Merges invoice history with PDF IDs.
- Returns typed models and separates parser/network errors.

### 9.2 What the integration does well

- Polls data on a configurable schedule.
- Fetches four sources concurrently.
- Preserves older radio history across refreshes.
- Creates meter and billing entities dynamically.
- Maintains external long-term statistics.
- Exposes refresh and connectivity state.
- Provides diagnostics with some redaction.
- Downloads invoice PDFs.
- Supports reauthentication and option reloads.

### 9.3 Remaining structural gaps

1. Multi-property support is experimental and lacks live two-property validation.
2. The service models a narrow read-only subset of the portal.
3. CSV/PDF table exports and portal charts are not implemented.
4. XLS remains the only complete structured history format used.
5. Invoice PDF content is opaque bytes.
6. Portal filters and sorting controls are not reproduced.
7. Alerts and paperless delivery remain server-side portal settings.
8. Account and incident mutations have no safe service boundary.
9. Derived HA values are not the same as portal calculations.
10. Portal-side weekly radio uploads and service polling have different latency expectations.

## 10. Recommended feature roadmap

This is research, not an implementation commitment. Priorities assume read-only safety and user value.

### P0: correctness and security before new features

1. **Credential and cookie log masking — implemented in 0.10.0.** Independent review passed the request, URL, snippet, export, and exception paths.
2. Fix `Device.last_consumption` on meter reset.
3. Fix billed `NaN` and decimal-comma handling.
4. **Optional invoice amount handling — implemented in 0.10.0.** None values no longer break the merge.
5. **Missing invoice device type — handled in 0.10.0.** It no longer crashes sensor setup.
6. Align the tested Home Assistant version with the manifest and statistics metadata.
7. Decide how stale billing data behaves after a transient parser failure.
8. Add real redacted fixtures for current billed and invoice XLS layouts.

### P1: high-value read-only features

1. **Invoice pagination — implemented.** All 63 live HTML invoice IDs were retrieved and matched to XLS history.
2. **CSV export methods.** Useful for users who want lightweight data, with explicit warnings about missing radio/billed columns.
3. **Portal chart image retrieval.** Return the actual portal PNG for a meter/date range.
4. **Invoice metadata extraction.** Start with issue date and period from PDF only if a reliable parser and tests exist.
5. **Multi-property selection — implemented experimentally.** One entry per property, private sessions, scoped identities, synthetic two-property tests, and live single-property verification are complete. Live multi-property validation remains the only acceptance gap.
6. **Incidence-code labels.** Add confirmed meanings for `47C9` and `47A5` from authoritative portal documentation.
7. **Raw/merged reading diagnostics.** Show whether a value was interpolated and preserve source provenance.

### P2: user-requested write features

These need a separate safety design:

1. Manual reading submission.
2. Incident submission.
3. Alert configuration.
4. Paperless-receipt setting.
5. Cost simulation.

Requirements for all write features:

- Explicit user action and confirmation.
- Clear preview of the request.
- No automatic retries that can duplicate submissions unless idempotent.
- Rate limiting.
- Audit record without secrets.
- Account/property context in the request.
- Safe handling of portal validation errors.
- Tests with mocked forms and responses.
- Documentation that distinguishes estimates from official bills.

### P3: avoid or defer

1. Automated registration/password recovery.
2. Account deletion/unlinking.
3. Email/password changes.
4. Blog/content scraping.
5. Replacing official invoice PDFs with reconstructed documents.

## 11. Portal-specific implementation notes

### 11.1 Export discovery

The library searches anchors for the export marker and rewrites the display selector to `e=2`. Live testing confirmed this finds the correct XLS link for radio, billed, and invoice tables.

Keep the invoice fallback URL, but log when fallback is used. A portal markup change should be visible rather than silently changing data sources.

### 11.2 HTML pages are stateful

Feature pages contain hidden method, account, and validation fields. Some buttons submit forms to switch property or digitalization state. A future generic crawler must distinguish:

- Navigation GET.
- Read-only search POST.
- Property-selection POST.
- Settings mutation POST.
- Incident/reading/financial POST.

Do not crawl by submitting every form.

### 11.3 The portal mixes data and presentation

A label can differ between HTML and XLS. A PDF can contain fields absent from both table formats. Treat each response as a separate contract with its own tests.

### 11.4 Date and time semantics

- Radio date headers are daily dates.
- Billed and invoice dates are date-only.
- The library assigns UTC midnight to radio dates.
- Home Assistant displays date-only billed timestamps in local time.
- The manual says radio data is uploaded weekly.

Do not add timezone assumptions to invoice/billed `date` fields.

### 11.5 Units

- Heating radio values use unit `UN` in the export; Home Assistant presents kWh based on device type.
- Water uses `m3`.
- Period alerts use m³.
- Daily alerts use liters/day.
- Invoice PDF line items have their own consumption units and pricing blocks.

Keep source units in diagnostics. Do not infer a conversion when the source only says `UN`.

### 11.6 Negative and zero consumption

The live billed export included zero and negative consumption. Possible causes include estimated readings, corrections, or meter changes; this audit did not establish the cause. Consumers must preserve values and surface anomalies rather than silently clamp them.

The library's interpolation treats a decrease as a reset and fills gaps with zero, but the actual decrease remains. This is separate from billed negative consumption.

## 12. Proposed tests from live findings

All fixtures must be synthetic or irreversibly redacted. Never commit live account pages, cookies, opaque IDs, serials, addresses, names, invoice numbers, or raw PDFs.

1. Radio XLS with metadata plus daily columns and decimal-comma strings.
2. Radio CSV with metadata only; assert the API reports that readings are absent.
3. Radio PDF metadata-only response.
4. Chart HTML containing `generarGraficoIndividual`.
5. Chart PNG response.
6. Billed XLS with old headers.
7. Billed XLS with new headers from issue #4.
8. Billed XLS with both header variants.
9. Billed XLS with `_` filler rows.
10. Billed XLS with blank numeric cells.
11. Billed XLS with decimal-comma strings.
12. Billed XLS with negative and zero consumption.
13. Billed incidence codes including unknown `47C9`/`47A5`.
14. Invoice HTML first page plus page-two link.
15. Invoice XLS larger than HTML page.
16. Invoice HTML/XLS merge with missing amount or type.
17. Individual invoice PDF with `%PDF` magic and expected content type.
18. Invoice PDF metadata extraction, if implemented.
19. Account selector with multiple properties.
20. Alert tabs with m³ and liters labels.
21. Manual-reading and incident forms are never submitted by read-only methods.

## 13. Open questions

1. Which accounts receive renamed billed XLS columns, and is the change permanent or rolling?
2. What are the authoritative descriptions of `47C9` and `47A5`?
3. Is the invoice-issued alert still available elsewhere in the portal?
4. What is the current official registration URL?
5. Can invoice PDF IDs be discovered for all history without scraping every page?
6. Does the PDF expose a stable machine-readable attachment or only rendered pages?
7. What causes the default dashboard error for this account?
8. Does the radio upload schedule always remain weekly?
9. Can one login safely switch between linked properties without affecting other clients?
10. Which Home Assistant users need multi-property support versus separate email accounts?

## 14. Final feature verdict

The existing service is a strong **read-only metering and billing integration**. It covers the portal's most valuable structured data: radio history, billed consumption, invoice history, and invoice PDF download.

It is not a complete portal client. It does not reproduce account management, manual readings, simulations, incidents, alerts, paperless delivery, charts, or the portal's full export formats.

The safest next step is not to add every portal action. First fix security and data correctness. Then add read-only formats and invoice/chart coverage. Treat multi-property support as an architectural change. Treat every write action as a separate, confirmed user operation.

## 15. Source references

- Live portal base: `https://oficina.ista.es/GesCon/`
- Official manual: `https://www.ista.com/fileadmin/media_ista/spain_es/Documents/Manuales/Manual_Calista_Abonados.pdf`
- Issue that exposed billed-column variation: `https://github.com/herruzo99/ista-calista/issues/4`
- Library architecture and known defects: `../../pycalista-ista/AGENTS.md`
- Integration architecture and known defects: `../AGENTS.md`

Live URLs are listed for reproducibility only. Authenticated query values are deliberately omitted.
