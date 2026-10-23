# Encryption keys

Three keys in `.env` protect the data. The installer and `make .env` generate them. Each is 64 hex characters; `openssl rand -hex 32` makes one, and `manage.sh check` reports a missing or malformed key.

| Setting | Protects | Used |
| --- | --- | --- |
| `DATA_ENCRYPTION_KEY` | The server's private keys, and the keyed hash that replaces each sender's address | Always |
| `DATABASE_FIELD_ENCRYPTION_KEY` | Linked accounts' platform tokens | When field encryption is on |
| `DATABASE_ENCRYPTION_KEY` | The whole SQLite database file (SQLCipher) | When encryption is on and the database is SQLite |

`template.env` turns both on with `DATABASE_FIELD_ENCRYPTION_ENABLED=true` and `DATABASE_ENCRYPTION_ENABLED=true`.

> [!CAUTION]
> Back up `.env` whenever you back up the database, store it apart ([Backup and restore](../operating/backup-restore.md)), and never change a key once the install holds data. Data encrypted with a lost or changed key can't be read again, and a new `DATA_ENCRYPTION_KEY` also gives every sender a new hash.
