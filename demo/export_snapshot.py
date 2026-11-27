"""Export the demo database as static API responses for the read-only web demo.

    .venv/Scripts/python.exe demo/export_snapshot.py

Every GET the React app makes is called through the real FastAPI app and
saved under demo/snapshot/ with the same path (api/overview -> overview.json,
api/runs/<id> -> runs/<id>.json, ...). The GitHub Pages build copies the
folder into the site as demo-data/ and builds the frontend in static mode.
"""
import json
import shutil

from fastapi.testclient import TestClient

import demo_env

settings = demo_env.activate()

from cn_job_agent.api import create_app  # noqa: E402

OUT = demo_env.SNAPSHOT


def save(path, body):
    target = OUT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(body, (bytes, bytearray)):
        target.write_bytes(body)
    elif isinstance(body, str):
        target.write_text(body, encoding="utf-8")
    else:
        target.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    with TestClient(create_app(settings, serve_frontend=False)) as client:
        def get(path):
            r = client.get(f"/api/{path}")
            r.raise_for_status()
            return r

        for name in ("overview", "model", "insights", "graph", "postings", "runs", "collections"):
            save(f"{name}.json", get(name).json())
        save("companies.json", get("companies").json())
        save("companies-all.json", get("companies?all=true").json())
        for posting in get("postings").json():
            save(f"postings/{posting['id']}.json", get(f"postings/{posting['id']}").json())
        for run in get("runs").json():
            save(f"runs/{run['id']}.json", get(f"runs/{run['id']}").json())
            report = client.get(f"/api/runs/{run['id']}/report")
            if report.status_code == 200:
                save(f"runs/{run['id']}/report.txt", report.text)
            materials = client.get(f"/api/runs/{run['id']}/materials")
            if materials.status_code == 200:
                save(f"runs/{run['id']}/materials.json", materials.json())
                for name in materials.json()["files"]:
                    save(f"runs/{run['id']}/materials/{name}", get(f"runs/{run['id']}/materials/{name}").content)
            interview = client.get(f"/api/runs/{run['id']}/interview")
            if interview.status_code == 200:
                save(f"runs/{run['id']}/interview.json", interview.json())
                save(f"runs/{run['id']}/interview.md", get(f"runs/{run['id']}/interview/interview.md").content)
        for collection in get("collections").json():
            save(f"collections/{collection['id']}.json", get(f"collections/{collection['id']}").json())
    files = [p for p in OUT.rglob("*") if p.is_file()]
    print(f"Wrote {len(files)} files to {OUT}")


if __name__ == "__main__":
    main()
