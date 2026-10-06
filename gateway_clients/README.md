# Gateway Clients Module

Registered clients are also readable via the REST API: see `GET /v1/gateway-clients` in the [REST API reference](../docs/openapi.json).

```bash
GATEWAY_CLIENTS_REGISTRY_FILE=data/gateway_clients/registry.json
```

> [!IMPORTANT]
> Use `./publisher.sh gateway-clients`, not `python3 -m publisher gateway-clients` directly. It resolves the install dir, loads `.env`, and runs as the service user so the registry file's ownership doesn't drift.

## Commands

```bash
./publisher.sh gateway-clients create --msisdn <MSISDN> --protocols <PROTOCOL,...> [--country] [--operator] [--operator-code]
./publisher.sh gateway-clients list [--msisdn] [--country] [--operator]
./publisher.sh gateway-clients update <MSISDN> [--country] [--operator] [--operator-code] [--protocols]
./publisher.sh gateway-clients delete <MSISDN>
./publisher.sh gateway-clients countries
./publisher.sh gateway-clients operators --country <COUNTRY>
```

`create` resolves country, operator, and PLMN code from the MSISDN automatically; you only supply the MSISDN and protocol(s). If that fails or is ambiguous (e.g. AT&T has nine PLMNs in the US), pass `--country`/`--operator`/`--operator-code` directly. The error message lists candidates when ambiguous. This is common for US/Canada numbers, since `phonenumbers` has little NANP carrier data.

## MCC/MNC (PLMN) Lookup

Resolution uses `phonenumbers` to get a country, ISO region, and carrier name, then matches the carrier against a PLMN table scoped to that region (needed since NANP countries share country code 1). Still best-effort, and only auto-applied when the match is unambiguous.

The table is two files, checked in order:

- `mcc_mnc_overrides.json`: admin-managed, checked first; kept next to the registry (`data/gateway_clients/` by default)
- `mcc_mnc_table.json` (in `publisher/gateway_clients/`): vendored snapshot of [musalbas/mcc-mnc-table](https://github.com/musalbas/mcc-mnc-table).

```bash
./publisher.sh gateway-clients mcc-mnc list [--country-code] [--network] [--iso]
./publisher.sh gateway-clients mcc-mnc add-override --mcc <MCC> --mnc <MNC> --country-code <CC> --network <NAME> --country <COUNTRY> [--iso <ISO>]
./publisher.sh gateway-clients mcc-mnc remove-override --mcc <MCC> --mnc <MNC>
```

Commit override additions. They're general PLMN fixes useful to any deployment, not local state.
