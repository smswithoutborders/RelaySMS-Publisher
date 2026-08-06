# Gateway Clients Module

Registered clients are also readable via the REST API: see [List Gateway Clients](../docs/rest.md#2-list-gateway-clients).

```bash
GATEWAY_CLIENTS_REGISTRY_FILE=gateway_clients/registry.json
```

> [!IMPORTANT]
> Use `./gateway-clients.sh`, not `python3 -m gateway_clients.cli` directly. It resolves the install dir, loads `.env`, and runs as the service user so the registry file's ownership doesn't drift.

## Commands

```bash
./gateway-clients.sh create --msisdn <MSISDN> --protocols <PROTOCOL,...> [--country] [--operator] [--operator-code]
./gateway-clients.sh list [--msisdn] [--country] [--operator]
./gateway-clients.sh update <MSISDN> [--country] [--operator] [--operator-code] [--protocols]
./gateway-clients.sh delete <MSISDN>
./gateway-clients.sh countries
./gateway-clients.sh operators --country <COUNTRY>
```

`create` resolves country, operator, and PLMN code from the MSISDN automatically; you only supply the MSISDN and protocol(s). If that fails or is ambiguous (e.g. AT&T has nine PLMNs in the US), pass `--country`/`--operator`/`--operator-code` directly. The error message lists candidates when ambiguous. This is common for US/Canada numbers, since `phonenumbers` has little NANP carrier data.

## MCC/MNC (PLMN) Lookup

Resolution uses `phonenumbers` to get a country, ISO region, and carrier name, then matches the carrier against a PLMN table scoped to that region (needed since NANP countries share country code 1). Still best-effort, and only auto-applied when the match is unambiguous.

The table is two files, checked in order:

- `mcc_mnc_overrides.json`: admin-managed, checked first
- `mcc_mnc_table.json`: vendored snapshot of [musalbas/mcc-mnc-table](https://github.com/musalbas/mcc-mnc-table).

```bash
./gateway-clients.sh mcc-mnc list [--country-code] [--network] [--iso]
./gateway-clients.sh mcc-mnc add-override --mcc <MCC> --mnc <MNC> --country-code <CC> --network <NAME> --country <COUNTRY> [--iso <ISO>]
./gateway-clients.sh mcc-mnc remove-override --mcc <MCC> --mnc <MNC>
```

Commit override additions. They're general PLMN fixes useful to any deployment, not local state.
