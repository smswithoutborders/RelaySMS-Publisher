# Gateway Clients

Gateway clients are the phone numbers that relay SMS to this server. They're stored in the `gateway_clients` table and listed publicly at `GET /v1/gateway-clients`; credentials with `gc:read` and `gc:write` manage them over the [REST API](../docs/rest.md#managing-gateway-clients). Every change is in the audit log.

## Commands

```bash
./publisher.sh gateway-clients suggest <MSISDN>                 # details and PLMN candidates; saves nothing
./publisher.sh gateway-clients create --msisdn <MSISDN> --protocols <PROTOCOL,...> [--country] [--operator] [--operator-code]
./publisher.sh gateway-clients list [--msisdn] [--country] [--operator]
./publisher.sh gateway-clients update <MSISDN> [--country] [--operator] [--operator-code] [--protocols]
./publisher.sh gateway-clients disable <MSISDN>                 # hide it from the public list
./publisher.sh gateway-clients enable <MSISDN>
./publisher.sh gateway-clients delete <MSISDN>
./publisher.sh gateway-clients countries
./publisher.sh gateway-clients operators --country <COUNTRY>
./publisher.sh gateway-clients mcc-mnc list [--country-code] [--network] [--iso]   # search the PLMN table
```

`create` fills in what you leave out from `suggest`, the PLMN code only when it's unambiguous. Otherwise pick a candidate and pass it with `--operator-code`.

## How Suggest Works

`phonenumbers` gives the number's country, region and carrier name. The carrier is matched against that region's operators in `publisher/gateway_clients/mcc_mnc_table.json`, a vendored snapshot of [musalbas/mcc-mnc-table](https://github.com/musalbas/mcc-mnc-table). A territory without rows of its own, like Guernsey, uses its calling code's main region.

Names are compared word by word, ignoring case, accents, company-type words ("Telecom", "Ltd", "Mobile") and the country's name, so "MTN Cameroon" matches "MTN" and "Beeline" matches "Bee Line/Unitel". Words many of the region's networks share count only weakly.

| `match` | Candidates |
| --- | --- |
| `carrier` | Networks matching the carrier, best first. The PLMN code is filled in only when they all share one. |
| `region` | Every operator in the country, because the carrier is unknown (common for US and Canadian numbers) or matched nothing |
| `none` | None: the number couldn't be placed. Enter the details yourself. |

> [!TIP]
> A PLMN missing from the snapshot can still be entered with `--operator-code`.

## Upgrading From the JSON Registry

Migration 019 imports `data/gateway_clients/registry.json` (or `GATEWAY_CLIENTS_REGISTRY_FILE`, if `.env` still sets it). MCC/MNC overrides are no longer used; the migration logs any it finds instead. Both files can then be deleted.
