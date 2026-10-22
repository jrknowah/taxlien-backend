# Tax Lien Analyzer – Backend

FastAPI service for collecting and browsing Mississippi tax lien / tax-forfeited parcel data.

## Setup

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
uvicorn main:app --reload
```

## Data sync

`sync.py` loads public data into a local SQLite database:

| Source | Table | Counties | What it is |
| ------ | ----- | -------- | ---------- |
| [MS Secretary of State tax-forfeited inventory](https://www.sos.ms.gov/tfsearch/) | `parcels` | any | State-owned parcels never redeemed after a tax sale; bought by application |
| [Hinds tax sale files](https://www.co.hinds.ms.us/pgs/taxsalefiles.asp) | `liens` | Hinds | Pre-sale list and sale results (buyer, overbid) |
| [Jackson annual tax sale list](https://www.co.jackson.ms.us/376/Annual-Sale-of-Delinquent-Taxes) | `liens` | Jackson | Preliminary pre-sale list (no results published) |

Monroe and Harrison don't post a sale list online (Monroe prints it in the
newspaper; Harrison's site blocks automated requests), so use `/upload` for those.
Lien sale dates are the statutory last Monday of August after the tax year.

```bash
python sync.py                              # default counties: Monroe, Hinds, Jackson, Harrison
python sync.py --counties Rankin Madison    # any Mississippi county
python sync.py --no-details                 # listing only (skips one request per new parcel)
python sync.py --only liens                 # just the county sale lists
```

Parcels that drop out of the inventory (sold or redeemed) are kept with `active = 0`.
Per-parcel details (tax year, tax sale date, acres, full legal description) are fetched
only for parcels not seen before, so repeat syncs are quick.

## API

- `GET /parcels?county=Hinds&min_value=5000&limit=50&offset=0` – stored parcels
  (`include_inactive=true` to include sold/redeemed ones)
- `GET /liens?county=Hinds&tax_year=2024&status=sold&min_face=500` – county tax sale liens.
  `status` is `offered`, `sold`, `struck_to_state` or `not_sold`. Each result has `metrics`:
  redemption deadline, months elapsed, accrued interest, redemption amount, and return on
  outlay (face + overbid) to date and if redeemed at the deadline. These assume 1.5%/month on
  the face amount, no interest on the overbid, and a 2-year redemption period; verify against
  the current Mississippi Code.
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
