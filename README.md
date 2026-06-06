# Event Registration API

A REST API for creating events, managing seat capacity, and registering users — built with FastAPI + SQLite.

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

API: http://127.0.0.1:8000  
Swagger docs: http://127.0.0.1:8000/docs  
ReDoc: http://127.0.0.1:8000/redoc

## Endpoints

| Method   | URL                                  | Description                    |
|----------|--------------------------------------|--------------------------------|
| `POST`   | `/events`                            | Create event                   |
| `GET`    | `/events`                            | List events (sort + filter)    |
| `GET`    | `/events/{id}`                       | Get single event               |
| `PATCH`  | `/events/{id}`                       | Partially update event         |
| `DELETE` | `/events/{id}`                       | Delete event                   |
| `GET`    | `/events/{id}/registrations`         | List active registrations      |
| `POST`   | `/events/{id}/register`              | Register a user                |
| `DELETE` | `/registrations/{id}`                | Cancel a registration          |

## Key Design Decisions

- **Race condition prevention**: seat decrement uses an atomic `UPDATE ... WHERE available_seats > 0`, checking rowcount to detect a full event — no read-then-write race window.
- **WAL mode**: SQLite runs in Write-Ahead Logging mode for safe concurrent reads during writes.
- **Three-layer validation**: every constraint (seats > 0, future date, unique name) is enforced at the Pydantic schema layer, ORM validator layer, and DB constraint layer.
- **Consistent error shape**: all errors return `{"error": "ERROR_CODE", "message": "..."}`.