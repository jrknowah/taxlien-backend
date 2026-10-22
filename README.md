# Tax Lien Analyzer – Backend

FastAPI service for collecting and browsing Mississippi tax lien / tax-forfeited parcel data.

## Setup

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
uvicorn main:app --reload
```

## Data sync

`sync.py` pulls the Mississippi Secretary of State tax-forfeited land inventory
(<https://www.sos.ms.gov/tfsearch/>) into a local SQLite database.

```bash
python sync.py                              # default counties: Monroe, Hinds, Jackson, Harrison
python sync.py --counties Rankin Madison    # any Mississippi county
python sync.py --no-details                 # listing only (skips one request per new parcel)
```

Parcels that drop out of the inventory (sold or redeemed) are kept with `active = 0`.
Per-parcel details (tax year, tax sale date, acres, full legal description) are fetched
only for parcels not seen before, so repeat syncs are quick.

## API

- `GET /parcels?county=Hinds&min_value=5000&limit=50&offset=0` – stored parcels
  (`include_inactive=true` to include sold/redeemed ones)
- `POST /upload` – preview a CSV file

## Configuration

| Variable          | Default                  | Purpose                                                     |
| ----------------- | ------------------------ | ----------------------------------------------------------- |
| `DATABASE_PATH`   | `taxliens.db`            | SQLite file                                                 |
| `SYNC_COUNTIES`   | `Monroe,Hinds,Jackson,Harrison` | Counties synced by default                           |
| `SYNC_CRON`       | unset (off)              | Run the sync inside the API on a schedule, e.g. `0 6 * * 1` |
| `ALLOWED_ORIGINS` | `http://localhost:5173`  | Comma-separated CORS origins                                |
| `MAX_UPLOAD_BYTES`| `10485760`               | Upload size limit                                           |

`SYNC_CRON` runs in every uvicorn worker, so with more than one worker schedule
`python sync.py` with cron instead.

## Tests

```bash
pytest
```
