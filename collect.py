"""Public notice metadata feed; no accounts or messaging credentials."""
import json
import time
from monitor import ROOT, Fetcher, load_list, detail, save, scan


def main():
    config = json.loads((ROOT / "config.json").read_text())
    state = json.loads((ROOT / "state.json").read_text())
    fetcher = Fetcher()
    report = scan(config, state, fetcher)
    # Validate a real detail page even when the listing is unchanged.
    if not report["errors"]:
        try:
            source = config["sources"][0]
            sample = next(iter(load_list(fetcher, source).values()))
            body = detail(fetcher, sample, source)
            report["sample_body_chars"] = len(body)
        except Exception as exc:
            report["errors"].append("Detail audit: " + type(exc).__name__)
    save(ROOT / "state.json", state)
    # Retain events for consumer recovery. Contains titles, links and matched terms only.
    feed = {"version": 1, "checked_at": report["checked_at"],
            "published_at": time.time(), "pending": state["pending"],
            "sources": report["sources"], "errors": report["errors"]}
    save(ROOT / "feed.json", feed)
    print(json.dumps({k: v for k, v in report.items() if k != "items"}, ensure_ascii=False))
    return bool(report["errors"])


if __name__ == "__main__":
    raise SystemExit(main())
