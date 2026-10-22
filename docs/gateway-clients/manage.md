# Managing gateway clients

Gateway clients are the phone numbers that relay SMS to this server. The enabled ones are listed publicly at `GET /v1/gateway-clients`. Credentials with `gc:read` and `gc:write` can manage them over the [REST API](../reference/rest-api.md#managing-gateway-clients). Every change is recorded in the [audit log](../reference/rest-api.md#audit-events).

## Commands

```bash
sudo ./publisher.sh gateway-clients suggest <MSISDN>                 # details and PLMN candidates; saves nothing
sudo ./publisher.sh gateway-clients create --msisdn <MSISDN> --protocols <PROTOCOL,...> [--country <COUNTRY>] [--operator <OPERATOR>] [--operator-code <PLMN>]
sudo ./publisher.sh gateway-clients list [--msisdn <MSISDN>] [--country <COUNTRY>] [--operator <OPERATOR>]
sudo ./publisher.sh gateway-clients update <MSISDN> [--country <COUNTRY>] [--operator <OPERATOR>] [--operator-code <PLMN>] [--protocols <PROTOCOL,...>]
sudo ./publisher.sh gateway-clients disable <MSISDN>                 # hide it from the public list
sudo ./publisher.sh gateway-clients enable <MSISDN>
sudo ./publisher.sh gateway-clients delete <MSISDN>
sudo ./publisher.sh gateway-clients countries
sudo ./publisher.sh gateway-clients operators --country <COUNTRY>
sudo ./publisher.sh gateway-clients mcc-mnc list [--country-code <CODE>] [--network <NAME>] [--iso <ISO>]   # search the PLMN table
```

`create` fills in any of `--country`, `--operator` and `--operator-code` you leave out with what `suggest` finds. It fills the PLMN code (MCC+MNC) only when every candidate shares it; otherwise run `suggest`, pick a candidate and pass it with `--operator-code`.

## How suggest works

`phonenumbers` gives the number's country, region and carrier name. The carrier is matched against that region's operators in `publisher/gateway_clients/mcc_mnc_table.json`, a vendored snapshot of [musalbas/mcc-mnc-table](https://github.com/musalbas/mcc-mnc-table). A territory without rows of its own, like Guernsey, uses its calling code's main region.

Names are compared word by word, ignoring case, accents, company-type words ("Telecom", "Ltd", "Mobile") and the country's name, so "MTN Cameroon" matches "MTN" and "Beeline" matches "Bee Line/Unitel". Words many of the region's networks share count only weakly.

| `match` | Candidates |
| --- | --- |
| `carrier` | Networks matching the carrier, best first. The PLMN code is filled in only when they all share one. |
| `region` | Every operator in the country, because the carrier is unknown (common for US and Canadian numbers) or matched nothing |
| `none` | None: the number couldn't be placed. Enter the details yourself. |

> [!TIP]
> A PLMN missing from the snapshot can still be entered with `--operator-code`.

## Upgrading from the JSON registry

Migration 019 imports `data/gateway_clients/registry.json` (or `GATEWAY_CLIENTS_REGISTRY_FILE`, if `.env` sets it). It logs any entries in `mcc_mnc_overrides.json` without importing them. Both files can then be deleted.
