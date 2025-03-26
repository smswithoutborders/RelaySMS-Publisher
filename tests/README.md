# Test Configuration

## Instructions

1. Copy the `test_config_template.ini` file to `test_config.ini`:

   ```sh
   cp tests/test_config_template.ini tests/test_config.ini
   ```

2. Update the `test_config.ini` file with the appropriate values for your environment.

3. The `test_config.ini` file is ignored by git and should not be committed to the repository.

# Running Tests

## Installation

First, ensure you have all the necessary dependencies installed. You can install the required packages using pip:

```sh
pip install -r requirements.txt
pip install -r requirements-test.txt
```

## Running Tests

To run the tests, you can use the following command:

```sh
pytest --env=<environment>
```

Replace `<environment>` with one of the following options: `local`, `staging`, or `prod`.

For example, to run the tests in the local environment:

```sh
pytest --env=local
```

## Running Isolated Test Suites

To run a specific test file, use the following command:

```sh
pytest --env=<environment> path/to/test_file.py
```

For example, to run the tests in `test_publishing.py` in the local environment:

```sh
pytest --env=local tests/test_publishing.py
```

## Additional Resources

For more information on running tests with pytest, refer to the [pytest documentation](https://docs.pytest.org/en/stable/how-to/usage.html).
