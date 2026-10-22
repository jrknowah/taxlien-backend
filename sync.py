"""Pull parcel data from public sources into the local database.

Run once:   python sync.py
            python sync.py --counties Hinds Jackson --no-details
            python sync.py --only liens
"""
import argparse
import logging
import os

import db
from connectors import hinds, jackson, ms_sos

log = logging.getLogger("sync")

DEFAULT_COUNTIES = ["Monroe", "Hinds", "Jackson", "Harrison"]


def configured_counties() -> list[str]:
    raw = os.getenv("SYNC_COUNTIES")
    return [c.strip() for c in raw.split(",") if c.strip()] if raw else DEFAULT_COUNTIES


def sync_ms_sos(counties=None, details=True, client=None, conn=None) -> dict:
    """Refresh the SOS forfeited-land inventory. Returns per-county stats."""
    client = client or ms_sos.SOSClient()
    conn = conn or db.connect()
    stats = {}
    for county in counties or configured_counties():
        seen_at = db.now()
        parcels = client.search_county(county)
        known = db.existing_ids(conn, ms_sos.SOURCE, county)
        new = [p for p in parcels if p["source_id"] not in known]
        if details:
            # Detail is one request per parcel, so only fetch it for new ones.
            for p in new:
                p.update(client.parcel_detail(p["source_id"]))
        with conn:
            db.upsert_parcels(conn, parcels, seen_at)
            # An empty listing for a county we already track more likely means
            # the site changed than that every parcel sold at once.
            if not parcels and known:
                log.warning("%s: no parcels returned; leaving existing records active", county)
                removed = 0
            else:
                seen = {p["source_id"] for p in parcels}
                removed = db.deactivate_missing(conn, ms_sos.SOURCE, county, seen)
        stats[county] = {"listed": len(parcels), "new": len(new), "removed": removed}
        log.info("%s: %s", county, stats[county])
    return stats


LIEN_SOURCES = {"Hinds": hinds.fetch, "Jackson": jackson.fetch}


def sync_liens(counties=None, conn=None, client=None) -> dict:
    """Load county tax sale lists for the counties that publish one."""
    conn = conn or db.connect()
    stats = {}
    for county in counties or configured_counties():
        fetch = LIEN_SOURCES.get(county.title())
        if not fetch:
            continue
        try:
            liens = fetch(client) if client else fetch()
        except Exception as e:
            log.exception("%s lien sync failed", county)
            stats[county.title()] = {"error": str(e)}
            continue
        with conn:
            db.upsert_liens(conn, liens, db.now())
        stats[county.title()] = {"liens": len(liens)}
        log.info("%s liens: %s", county, stats[county.title()])
    return stats


def sync_all(counties=None, details=True) -> dict:
    """Run every source; one failing source doesn't stop the others."""
    results = {}
    for name, job in (("forfeited", lambda: sync_ms_sos(counties, details=details)),
                      ("liens", lambda: sync_liens(counties))):
        try:
            results[name] = job()
        except Exception as e:
            log.exception("%s sync failed", name)
            results[name] = {"error": str(e)}
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counties", nargs="+", help="defaults to SYNC_COUNTIES or %s" % DEFAULT_COUNTIES)
    parser.add_argument("--no-details", action="store_true", help="skip per-parcel detail requests")
    parser.add_argument("--only", choices=["forfeited", "liens"], help="run a single source")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.only == "forfeited":
        sync_ms_sos(args.counties, details=not args.no_details)
    elif args.only == "liens":
        sync_liens(args.counties)
    else:
        sync_all(args.counties, details=not args.no_details)


if __name__ == "__main__":
    main()
