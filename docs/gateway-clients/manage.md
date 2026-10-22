# Managing gateway clients

A gateway client is a phone number that relays the SMS people send to this server: an Android phone running Deku SMS, or a Twilio number. Register each number here so the RelaySMS app lists it, then [connect its relay](connect-a-relay.md). The enabled ones are listed publicly at `GET /v1/gateway-clients`. Credentials with `gc:read` and `gc:write` can manage them over the [REST API](../reference/rest-api.md#managing-gateway-clients). Every change is recorded in the [audit log](../reference/rest-api.md#audit-events).

## Commands

| Command | Does |
| --- | --- |
| `gateway-clients suggest <MSISDN>` | Shows the number's details and PLMN candidates; saves nothing |
| `gateway-clients create --msisdn <MSISDN> --protocols <PROTOCOLS>` | Registers a number; also takes `--country`, `--operator` and `--operator-code` |
| `gateway-clients list` | Lists them; filter with `--msisdn`, `--country` or `--operator` |
| `gateway-clients update <MSISDN>` | Changes `--country`, `--operator`, `--operator-code` or `--protocols` |
| `gateway-clients disable <MSISDN>` | Hides it from the public list |
| `gateway-clients enable <MSISDN>` | Lists it publicly again |
| `gateway-clients delete <MSISDN>` | Removes it |
| `gateway-clients countries` | Lists the countries that have a gateway client |
| `gateway-clients operators --country <COUNTRY>` | Lists the operators of that country's gateway clients |
| `gateway-clients mcc-mnc list` | Searches the PLMN table; filter with `--country-code`, `--network` or `--iso` |

Prefix each with `sudo ./publisher.sh`. `<PROTOCOLS>` is comma-separated, such as `https,smtp`. For example:

```bash
sudo ./publisher.sh gateway-clients create --msisdn +237600000000 --protocols https
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

A PLMN missing from the snapshot can still be entered with `--operator-code`.

## Upgrading from the JSON registry

Migration 019 imports `data/gateway_clients/registry.json` (or `GATEWAY_CLIENTS_REGISTRY_FILE`, if `.env` sets it). It logs any entries in `mcc_mnc_overrides.json` without importing them. Both files can then be deleted.
