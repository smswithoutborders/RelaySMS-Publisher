# Publisher Specifications

## Table of Contents

- [Content Format](#content-format)
- [Payload Format](#payload-format)

## Content Format

The Publisher supports four formats of content:

1. **Email format**: `from:to:cc:bcc:subject:body`

   - Example: Gmail

2. **Text format**: `sender:text`

   - Example: Twitter

3. **Message format**: `sender:receiver:message`

   - Example: Telegram

4. **Test format**: `start_time:id:msisdn`

   - Example: ReliabilityTest
[ReliabilityTest Specification](/docs/reliability_test.md) 

## Supported Payload Versions

| **Version**              | **Hexadecimal Value** | **Decimal Value** | **Description**                                             |
| ------------------------ | --------------------- | ----------------- | ----------------------------------------------------------- |
| [v0](#payload-format-v0) | `None`                | `None`            | No explicit version marker, backward-compatible formats.    |
| [v1](#payload-format-v1) | `0x01`                | `1`               | Includes a version marker as the first byte of the payload. |

## Payload Format V0

> [See available versions](#supported-payload-versions)

### Message Payload

- **Format**:
  - **4 bytes**: Ciphertext Length.
  - **1 byte**: Platform shortcode. For a list of supported platforms and their corresponding shortcodes, refer to the [Supported Platforms](/docs/grpc.md#supported-platforms) section.
  - **Variable**: Ciphertext.
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

| **Payload Type**                    | **Description**              |
| ----------------------------------- | ---------------------------- |
| [Message Payload](#message-payload) | Contains a client public key |

### Message Payload

- **Format**:
  - **1 byte**: Version Marker. [See available versions](#supported-payload-versions).
  - **2 bytes**: Ciphertext Length.
  - **1 bytes**: Device ID Length.
  - **1 bytes**: Access Token Length.
  - **1 bytes**: Refresh Token Length.
  - **1 byte**: Platform shortcode.
  - **Variable**: Ciphertext.
  - **Variable**: Device ID.
  - **Variable**: Access Token.
  - **Variable**: Refresh Token.
  - **2 bytes**: Language Code (ISO 639-1 format).

> [!NOTE]
>
> For detailed instructions on using the Double Ratchet algorithm to create ciphertext, refer to the [smswithoutborders_lib_sig documentation](https://github.com/smswithoutborders/lib_signal_double_ratchet_python?tab=readme-ov-file#double-ratchet-implementations).

#### Visual Representation:

```plaintext
+----------------+-------------------+------------------+---------------------+----------------------+--------------------+-----------------+-----------------+-----------------+-----------------+---------------+
| Version Marker | Ciphertext Length | Device ID Length | Access Token Length | Refresh Token Length | Platform shortcode | Ciphertext      | Device ID       | Access Token    | Refresh Token   | Language Code |
| (1 byte)       | (2 bytes)         | (1 byte)         | (1 byte)            | (1 byte)             | (1 byte)           | (Variable size) | (Variable size) | (Variable size) | (Variable size) | (2 bytes)     |
+----------------+-------------------+------------------+---------------------+----------------------+--------------------+-----------------+-----------------+-----------------+-----------------+---------------+
```

```python
version_marker = b'\x0a'
platform_shortcode = b'g'
language_code = b'en'
device_id = b'...'
access_token = b'...'
refresh_token = b'...'

payload = (
   version_marker +
   struct.pack("<H", len(encrypted_content)) +
   bytes([len(device_id)]) +
   bytes([len(access_token)]) +
   bytes([len(refresh_token)]) +
   platform_shortcode +
   encrypted_content +
   device_id +
   access_token +
   refresh_token +
   language_code
)
encoded = base64.b64encode(payload).decode("utf-8")
print(encoded)
```
