# Publisher Specifications

## Table of Contents

- [Content Format](#content-format)
  - [Content Format V0](#content-format-v0)
  - [Content Format V1](#content-format-v1)
  - [Content Format V2](#content-format-v2)
- [Payload Format](#supported-payload-versions)
  - [Payload Format V0](#payload-format-v0)
  - [Payload Format V1](#payload-format-v1)
  - [Payload Format V2](#payload-format-v2)

## Content Format

### Content Format V0

> [!NOTE]
>
> For detailed instructions on encrypting the content format using the Double Ratchet algorithm, refer to the [smswithoutborders_lib_sig documentation](https://github.com/smswithoutborders/lib_signal_double_ratchet_python?tab=readme-ov-file#double-ratchet-implementations).

1. **Email format**: `from:to:cc:bcc:subject:body[:access_token:refresh_token]`

   - Example: Gmail
   - Square brackets (`[]`) indicate optional fields.

2. **Text format**: `sender:text[:access_token:refresh_token]`

   - Example: Twitter
   - Square brackets (`[]`) indicate optional fields.

3. **Message format**: `sender:receiver:message`

   - Example: Telegram

4. **Test format**: `test_id`

   - Example: reliability
     [ReliabilityTest Specification](/docs/reliability_test.md)

### Content Format V1

> [!NOTE]
>
> For detailed instructions on encrypting the content format using the Double Ratchet algorithm, refer to the [smswithoutborders_lib_sig documentation](https://github.com/smswithoutborders/lib_signal_double_ratchet_python?tab=readme-ov-file#double-ratchet-implementations).

> [!NOTE]
>
> All service types use the same structure, but fields not applicable to a specific service type will have their length bytes set to `0`, and no value bytes will follow for those fields.
>
> **All 2-byte length fields are encoded as unsigned little-endian.**

1. **Email format**: Binary-encoded fields with the following structure:

   - **1 byte**: Length of `from` field.
   - **2 bytes**: Length of `to` field.
   - **2 bytes**: Length of `cc` field.
   - **2 bytes**: Length of `bcc` field.
   - **1 byte**: Length of `subject` field.
   - **2 bytes**: Length of `body` field.
   - **1 byte**: Length of `access_token` field (optional).
   - **1 byte**: Length of `refresh_token` field (optional).
   - **Variable**: Value of `from` field.
   - **Variable**: Value of `to` field.
   - **Variable**: Value of `cc` field.
   - **Variable**: Value of `bcc` field.
   - **Variable**: Value of `subject` field.
   - **Variable**: Value of `body` field.
   - **Variable**: Value of `access_token` field (if present).
   - **Variable**: Value of `refresh_token` field (if present).

2. **Text format**: Binary-encoded fields with the following structure:

   - **1 byte**: Length of `from` field.
   - **2 bytes**: Length of `to` field (set to `0`).
   - **2 bytes**: Length of `cc` field (set to `0`).
   - **2 bytes**: Length of `bcc` field (set to `0`).
   - **1 byte**: Length of `subject` field (set to `0`).
   - **2 bytes**: Length of `body` field.
   - **1 byte**: Length of `access_token` field (optional).
   - **1 byte**: Length of `refresh_token` field (optional).
   - **Variable**: Value of `from` field.
   - **Variable**: Value of `body` field.
   - **Variable**: Value of `access_token` field (if present).
   - **Variable**: Value of `refresh_token` field (if present).

3. **Message format**: Binary-encoded fields with the following structure:

   - **1 byte**: Length of `from` field.
   - **2 bytes**: Length of `to` field.
   - **2 bytes**: Length of `cc` field (set to `0`).
   - **2 bytes**: Length of `bcc` field (set to `0`).
   - **1 byte**: Length of `subject` field (set to `0`).
   - **2 bytes**: Length of `body` field.
   - **1 byte**: Length of `access_token` field (set to `0`).
   - **1 byte**: Length of `refresh_token` field (set to `0`).
   - **Variable**: Value of `from` field.
   - **Variable**: Value of `to` field.
   - **Variable**: Value of `body` field.

4. **Test format**: Binary-encoded fields with the following structure:

   - **1 byte**: Length of `from` field.
   - **2 bytes**: Length of `to` field (set to `0`).
   - **2 bytes**: Length of `cc` field (set to `0`).
   - **2 bytes**: Length of `bcc` field (set to `0`).
   - **1 byte**: Length of `subject` field (set to `0`).
   - **2 bytes**: Length of `body` field (set to `0`).
   - **1 byte**: Length of `access_token` field (set to `0`).
   - **1 byte**: Length of `refresh_token` field (set to `0`).
   - **Variable**: Value of `from` field (considered the test ID).

### Content Format V2

> [!NOTE]
>
> For detailed instructions on encrypting the content format using the Double Ratchet algorithm, refer to the [smswithoutborders_lib_sig documentation](https://github.com/smswithoutborders/lib_signal_double_ratchet_python?tab=readme-ov-file#double-ratchet-implementations).

> [!NOTE]
>
> All service types use the same structure, but fields not applicable to a specific service type will have their length bytes set to `0`, and no value bytes will follow for those fields.
>
> **All 2-byte length fields are encoded as unsigned little-endian.**

1. **Email format**: Binary-encoded fields with the following structure:

   - **1 byte**: Length of `from` field.
   - **2 bytes**: Length of `to` field.
   - **2 bytes**: Length of `cc` field.
   - **2 bytes**: Length of `bcc` field.
   - **1 byte**: Length of `subject` field.
   - **2 bytes**: Length of `body` field.
   - **2 bytes**: Length of `access_token` field (optional).
   - **2 bytes**: Length of `refresh_token` field (optional).
   - **Variable**: Value of `from` field.
   - **Variable**: Value of `to` field.
   - **Variable**: Value of `cc` field.
   - **Variable**: Value of `bcc` field.
   - **Variable**: Value of `subject` field.
   - **Variable**: Value of `body` field.
   - **Variable**: Value of `access_token` field (if present).
   - **Variable**: Value of `refresh_token` field (if present).

2. **Text format**: Binary-encoded fields with the following structure:

   - **1 byte**: Length of `from` field.
   - **2 bytes**: Length of `to` field (set to `0`).
   - **2 bytes**: Length of `cc` field (set to `0`).
   - **2 bytes**: Length of `bcc` field (set to `0`).
   - **1 byte**: Length of `subject` field (set to `0`).
   - **2 bytes**: Length of `body` field.
   - **2 byte**: Length of `access_token` field (optional).
   - **2 byte**: Length of `refresh_token` field (optional).
   - **Variable**: Value of `from` field.
   - **Variable**: Value of `body` field.
   - **Variable**: Value of `access_token` field (if present).
   - **Variable**: Value of `refresh_token` field (if present).

3. **Message format**: Binary-encoded fields with the following structure:

   - **1 byte**: Length of `from` field.
   - **2 bytes**: Length of `to` field.
   - **2 bytes**: Length of `cc` field (set to `0`).
   - **2 bytes**: Length of `bcc` field (set to `0`).
   - **1 byte**: Length of `subject` field (set to `0`).
   - **2 bytes**: Length of `body` field.
   - **2 byte**: Length of `access_token` field (set to `0`).
   - **2 byte**: Length of `refresh_token` field (set to `0`).
   - **Variable**: Value of `from` field.
   - **Variable**: Value of `to` field.
   - **Variable**: Value of `body` field.

4. **Test format**: Binary-encoded fields with the following structure:

   - **1 byte**: Length of `from` field.
   - **2 bytes**: Length of `to` field (set to `0`).
   - **2 bytes**: Length of `cc` field (set to `0`).
   - **2 bytes**: Length of `bcc` field (set to `0`).
   - **1 byte**: Length of `subject` field (set to `0`).
   - **2 bytes**: Length of `body` field (set to `0`).
   - **2 byte**: Length of `access_token` field (set to `0`).
   - **2 byte**: Length of `refresh_token` field (set to `0`).
   - **Variable**: Value of `from` field (considered the test ID).

## Supported Payload Versions

| **Version**              | **Hexadecimal Value** | **Decimal Value** | **Description**                                             |
| ------------------------ | --------------------- | ----------------- | ----------------------------------------------------------- |
| [v0](#payload-format-v0) | `None`                | `None`            | No explicit version marker, backward-compatible formats.    |
| [v1](#payload-format-v1) | `0x01`                | `1`               | Includes a version marker as the first byte of the payload. |
| [v2](#payload-format-v1) | `0x02`                | `2`               | Includes a version marker as the first byte of the payload. |

## Payload Format V0

> [See available versions](#supported-payload-versions)

### Message Payload

- **Format**:
  - **4 bytes**: Ciphertext Length.
  - **1 byte**: Platform shortcode. For a list of supported platforms and their corresponding shortcodes, refer to the [Supported Platforms](/docs/grpc.md#supported-platforms) section.
  - **Variable**: Ciphertext. (encrypted [Content Format V0](#content-format-v0)).
  - **Variable**: Device ID.

> [!NOTE]
>
> For detailed instructions on using the Double Ratchet algorithm to create ciphertext, refer to the [smswithoutborders_lib_sig documentation](https://github.com/smswithoutborders/lib_signal_double_ratchet_python?tab=readme-ov-file#double-ratchet-implementations).

#### Visual Representation:

```plaintext
+-------------------+--------------------+-------------------+-----------------+
| Ciphertext Length | Platform shortcode | Ciphertext        | Device ID       |
| (4 bytes)         | (1 byte)           | (Variable size)   | (Variable size) |
+-------------------+--------------------+-------------------+-----------------+
```

```python
platform_shortcode = b'g'
encrypted_content = b'...'
device_id = b'...'

payload = struct.pack("<i", len(encrypted_content)) + platform_shortcode + encrypted_content + device_id
encoded = base64.b64encode(payload).decode("utf-8")
print(encoded)
```

## Payload Format V1

> [See available versions](#supported-payload-versions)

### Message Payload

- **Format**:
  - **1 byte**: Version Marker. [See available versions](#supported-payload-versions).
  - **2 bytes**: Ciphertext Length.
  - **1 byte**: Device ID Length.
  - **1 byte**: Platform shortcode.
  - **Variable**: Ciphertext. (encrypted [Content Format V1](#content-format-v1)).
  - **Variable**: Device ID.
  - **2 bytes**: Language Code (ISO 639-1 format).

> [!NOTE]
>
> For detailed instructions on using the Double Ratchet algorithm to create ciphertext, refer to the [smswithoutborders_lib_sig documentation](https://github.com/smswithoutborders/lib_signal_double_ratchet_python?tab=readme-ov-file#double-ratchet-implementations).

#### Visual Representation:

```plaintext
+----------------+-------------------+------------------+--------------------+-----------------+-----------------+---------------+
| Version Marker | Ciphertext Length | Device ID Length | Platform shortcode | Ciphertext      | Device ID       | Language Code |
| (1 byte)       | (2 bytes)         | (1 byte)         | (1 byte)           | (Variable size) | (Variable size) | (2 bytes)     |
+----------------+-------------------+------------------+--------------------+-----------------+-----------------+---------------+
```

```python
version_marker = b'\x01'
platform_shortcode = b'g'
language_code = b'en'
device_id = b'...'
encrypted_content = b'...'

payload = (
   version_marker +
   struct.pack("<H", len(encrypted_content)) +
   bytes([len(device_id)]) +
   platform_shortcode +
   encrypted_content +
   device_id +
   language_code
)
encoded = base64.b64encode(payload).decode("utf-8")
print(encoded)
```

## Payload Format V2

> [See available versions](#supported-payload-versions)

### Message Payload

- **Format**:
  - **1 byte**: Version Marker. [See available versions](#supported-payload-versions).
  - **2 bytes**: Ciphertext Length.
  - **1 byte**: Device ID Length.
  - **1 byte**: Platform shortcode.
  - **Variable**: Ciphertext. (encrypted [Content Format V2](#content-format-v2)).
  - **Variable**: Device ID.
  - **2 bytes**: Language Code (ISO 639-1 format).

> [!NOTE]
>
> For detailed instructions on using the Double Ratchet algorithm to create ciphertext, refer to the [smswithoutborders_lib_sig documentation](https://github.com/smswithoutborders/lib_signal_double_ratchet_python?tab=readme-ov-file#double-ratchet-implementations).

#### Visual Representation:

```plaintext
+----------------+-------------------+------------------+--------------------+-----------------+-----------------+---------------+
| Version Marker | Ciphertext Length | Device ID Length | Platform shortcode | Ciphertext      | Device ID       | Language Code |
| (1 byte)       | (2 bytes)         | (1 byte)         | (1 byte)           | (Variable size) | (Variable size) | (2 bytes)     |
+----------------+-------------------+------------------+--------------------+-----------------+-----------------+---------------+
```

```python
version_marker = b'\x02'
platform_shortcode = b'g'
language_code = b'en'
device_id = b'...'
encrypted_content = b'...'

payload = (
   version_marker +
   struct.pack("<H", len(encrypted_content)) +
   bytes([len(device_id)]) +
   platform_shortcode +
   encrypted_content +
   device_id +
   language_code
)
encoded = base64.b64encode(payload).decode("utf-8")
print(encoded)
```
