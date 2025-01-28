# Publisher API

## Prerequisites

### Install Dependencies

Install the necessary dependencies from
`requirements.txt`. 

> [!TIP]
>
> It's recommended to set up a virtual environment to isolate your project's
> dependencies.

```bash
python3 -m venv venv
source venv/bin/activate
```

```bash
pip install -r requirements.txt
```

### Starting the Server

**Quick Start (for Development Only):**

   Run the FastAPI application server. By default, the server will run on `http://localhost:8000`.
   ```bash
  fastapi dev api_v1.py
   ```

  Access the API documentation at [http://localhost:8000/docs](http://localhost:8000/docs).



### Where to Find the Documentation

The API documentation is automatically generated and available here:

**Swagger UI** (Interactive):
   - URL: [http://localhost:8000/docs](http://localhost:8000/docs)
  

### Contributing

To contribute:

1. Fork the repository.
2. Create a feature branch: `git checkout -b feature-branch`.
3. Commit your changes: `git commit -m 'Add a new feature'`.
4. Push to the branch: `git push origin feature-branch`.
5. Open a Pull Request.

### License

This project is licensed under the GNU General Public License (GPL). See the [LICENSE](LICENSE) file for details.