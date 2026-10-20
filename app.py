"""
Item Tracking Dashboard — Web App.

Interface:
  GET  /                       Upload page for the two files
  POST /process                Receives the two files, runs the pipeline, returns JSON
  GET  /last_result.json       Latest processed JSON (for dashboard autoload)
  GET  /event_mapping.json     Serves the event-to-stage mapping
  GET  /dashboard              Serves the interactive dashboard
  GET  /health                 Healthcheck
"""

import json
import os
import threading
import webbrowser

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_from_directory,
)

from pipeline import run_pipeline

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MAPPING_FILE = os.path.join(APP_DIR, "event_mapping.json")
MAX_CONTENT_MB = int(os.environ.get("MAX_CONTENT_MB", "64"))

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_MB * 1024 * 1024

LAST_RESULT = {"data": None}


@app.route("/")
def index():
    return render_template("upload.html")


@app.route("/process", methods=["POST"])
def process():
    ops_file = request.files.get("operational")
    routing_file = request.files.get("routing")

    if ops_file is None or ops_file.filename == "":
        return jsonify({"error": "Operational Events file missing."}), 400
    if routing_file is None or routing_file.filename == "":
        return jsonify({"error": "Routing Events file missing."}), 400

    try:
        result = run_pipeline(
            ops_file.stream,
            routing_file.stream,
            ops_name=ops_file.filename,
            routing_name=routing_file.filename,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Error during processing: {exc}"}), 500

    LAST_RESULT["data"] = result

    payload = json.dumps(result, ensure_ascii=False, indent=1)

    if request.args.get("download") == "1":
        return Response(
            payload,
            mimetype="application/json",
            headers={
                "Content-Disposition": "attachment; filename=dashboard_data.json"
            },
        )

    return Response(payload, mimetype="application/json")


@app.route("/last_result.json")
def last_result():
    if LAST_RESULT["data"] is None:
        return jsonify({"error": "No data processed yet. Upload files first."}), 404
    return Response(
        json.dumps(LAST_RESULT["data"], ensure_ascii=False, indent=1),
        mimetype="application/json",
    )


@app.route("/event_mapping.json")
def event_mapping():
    return send_from_directory(APP_DIR, "event_mapping.json",
                               mimetype="application/json")


@app.route("/dashboard")
def dashboard():
    return send_from_directory(os.path.join(APP_DIR, "static"),
                               "dashboard.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


def _open_browser(port):
    webbrowser.open(f"http://localhost:{port}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))

    if os.environ.get("OPEN_BROWSER", "1") == "1":
        if not (app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true"):
            threading.Timer(1.0, _open_browser, args=(port,)).start()

    app.run(host="0.0.0.0", port=port, debug=False)
