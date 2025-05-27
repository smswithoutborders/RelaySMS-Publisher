# RelaySMS Publisher

RelaySMS Publisher allows users to publish content to online platforms (like Gmail, Twitter, Telegram) using SMS when internet connectivity is unavailable.

## Requirements

- **Python**: Version >= 3.8.10
- **Dependencies**: Install system packages:
  ```bash
  sudo apt install build-essential python3-dev
  ```

## Quick Start

1. **Setup virtual environment**:

   ```bash
   python3 -m venv venv
   . venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Download and compile protocol buffers**:

   ```bash
   make grpc-compile
   ```

3. **Start the server**:

   ```bash
   export GRPC_HOST=localhost
   export GRPC_PORT=8000
   # Additional environment variables as needed

   # Start the server
   python3 grpc_server.py
   ```

## Supported Platforms

The list of supported platforms is available in [platforms.json](resources/platforms.json) and can also be retrieved from the REST API at [https://publisher.smswithoutborders.com/platforms](https://publisher.smswithoutborders.com/platforms).

## Testing

For information on setting up and running tests, see the [Test Documentation](tests/README.md).

## Platform Adapters

Platform adapters can be used to extend RelaySMS Publisher's functionality. For more information, see the [Platforms Documentation](platforms/README.md).

## Documentation

- [gRPC API Documentation](docs/grpc.md)
- [Content and Payload Specifications](docs/specification.md)
- [REST API Documentation](https://publisher.smswithoutborders.com/docs)
- [Reliability Testing](docs/reliability_test.md)

## License

This project is licensed under the GNU General Public License (GPL) v3. See the [LICENSE](LICENSE.md) file for details.
