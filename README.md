# SMSWithoutBorders Publisher Documentation

## Supported Platforms

The list of supported platforms is available in
[platforms.json](resources/platforms.json).

## Requirements

- **Python**: Version >=
  [3.8.10](https://www.python.org/downloads/release/python-3810/)
- **Python Virtual Environments**:
  [Documentation](https://docs.python.org/3/tutorial/venv.html)

## Dependencies

### On Ubuntu

Install the necessary system packages:

```bash
sudo apt install build-essential python3-dev
```

## Installation

1. **Create a virtual environment:**

   ```bash
   python3 -m venv venv
   ```

2. **Activate the virtual environment:**

   ```bash
   . venv/bin/activate
   ```

3. **Install the required Python packages:**

   ```bash
   pip install -r requirements.txt
   ```

## Configuration

### Gmail

1. Obtain your credentials from the
   [Google Cloud Console](https://console.cloud.google.com/).
2. Set the `GMAIL_CREDENTIALS` environment variable to the path of your
   credentials file:

   ```bash
   export GMAIL_CREDENTIALS=path/to/gmail_credentials.json
   ```

   **Sample `gmail_credentials.json`**

   ```json
   {
     "web": {
       "client_id": "",
       "project_id": "",
       "auth_uri": "https://accounts.google.com/o/oauth2/auth",
       "token_uri": "https://oauth2.googleapis.com/token",
       "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
       "client_secret": "",
       "redirect_uris": ["http://localhost/callback/"],
       "javascript_origins": ["http://localhost"]
     }
   }
   ```

   > Only the first item in the `redirect_uris` is used for the OAuth2 flow.

### Twitter

1. Obtain your credentials from the
   [Twitter Developer Portal](https://developer.twitter.com/en/portal/).
2. Set the `TWITTER_CREDENTIALS` environment variable to the path of your
   credentials file:

   ```bash
   export TWITTER_CREDENTIALS=path/to/twitter_credentials.json
   ```

   **Sample `twitter_credentials.json`**

   ```json
   {
     "client_id": "",
     "client_secret": "",
     "redirect_uris": ["http://localhost/callback/"]
   }
   ```

   > Only the first item in the `redirect_uris` is used for the OAuth2 flow.

## Usage

### Download and Compile Protocol Buffers

```bash
make grpc-compile
```

### Start gRPC Server

Set the environment variables and start the server in one command:

```bash
GMAIL_CREDENTIALS=path/to/gmail_credentials.json \
TWITTER_CREDENTIALS=path/to/twitter_credentials.json \
GRPC_HOST=localhost \
GRPC_PORT=8000 \
GRPC_SSL_PORT=8001 \
VAULT_GRPC_HOST=localhost \
VAULT_GRPC_PORT=6000 \
VAULT_GRPC_SSL_PORT=6001 \
VAULT_GRPC_INTERNAL_PORT=6099 \
VAULT_GRPC_INTERNAL_SSL_PORT=6098 \
SSL_CERTIFICATE=path/to/certificate \
SSL_KEY=path/to/key \
python3 grpc_server.py
```

### References

1. [gRPC Documentation](docs/grpc.md)
2. [Specifications Documentation](/docs/specification.md)
   - [Content Format](/docs/specification.md#content-format)
   - [Payload Format](/docs//specification.md#payload-format)
3. [Publisher API Documentation](/docs/specification.md)
