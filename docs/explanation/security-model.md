# Security model

The RelaySMS protocol is described in the [technical whitepaper](relaysms-whitepaper.pdf). This page covers what the Publisher holds and who can read it.

## Keys

| Key | Where | Used for |
| --- | --- | --- |
| Server identity keys | 256 X25519 key pairs in the database | Every gRPC request and every payload; the only key for payloads sent without a linked account |
| Ephemeral key pools | Up to 256 client public keys and 256 server key pairs per linked account | One use each, by a payload or a token check; a successful use deletes the pair |
| [Encryption keys](../configuration/encryption-keys.md) | `.env` | Encrypting the private keys, the platform tokens and, with SQLite, the database file, and keying the sender hash |

The app refills a linked account's pools with the gRPC `SyncKeys` call. A failed publication leaves its key pair usable, so the same SMS can publish when it's sent again. A client must never encrypt different content with a key pair it has already used.

## What travels encrypted

- **Payloads from a linked account** are encrypted by the app with a pool key pair combined with an identity key, so the gateway client and the network carry only ciphertext.
- **Payloads sent without a linked account** are encrypted to an identity key alone, without forward secrecy: anyone who later obtains the identity private keys can decrypt recorded ones.
- **gRPC requests** carry their payload (`x-payload-bin`) encrypted to an identity key. A request is refused if its nonce was already seen, or if its timestamp is more than `NONCE_TTL_SECONDS` from the server's clock. The other request fields, such as phone numbers, login codes and two-step passwords, rely on TLS, from nginx or `GRPC_TLS_ENABLED`.
- **The REST API** takes payloads without credentials, and **the email listener** only from [allowed senders](../configuration/smtp-transport.md#allowlist). Either way, a payload only publishes if it decrypts with a linked account's keys, or passes the [offline publishing](../configuration/offline-publishing.md) rules.

## What the operator can see

| Data | Stored as |
| --- | --- |
| Platform tokens | Encrypted with `DATABASE_FIELD_ENCRYPTION_KEY` while `DATABASE_FIELD_ENCRYPTION_ENABLED` is on, as `template.env` sets it |
| Private keys | Encrypted with `DATA_ENCRYPTION_KEY` |
| Sender phone numbers | Replaced with a keyed hash before anything is stored |
| Message content | Ciphertext while queued, and while a multi-part payload waits for its segments; decrypted only in memory, in the worker and the adapter process it hands it to |
| Publication stats | Platform, protocol, status, country code, failure reason and time |

## Adapters

An adapter runs as the service user, so it can read `.env` and the database. `PLATFORMS_GITHUB_ORGS` limits which orgs administrators can install from over the REST API.

## Who can read what

Anyone holding both `.env` and the database can decrypt the tokens, publish as the linked accounts, and decrypt recorded payloads sent without a linked account. With field encryption off, the database alone exposes the tokens. Protect them as [Backup and restore](../operating/backup-restore.md) and [Security hardening](../operating/security-hardening.md) describe.
