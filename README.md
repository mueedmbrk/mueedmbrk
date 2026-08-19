<h1 align="center">👴 Elder Care Monitoring System</h1>

<p align="center">
  <b>🎥 Real-time computer vision that spots a fall and reaches a carer in seconds</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/OpenCV-4.9-5C3EE8?logo=opencv&logoColor=white" alt="OpenCV">
  <img src="https://img.shields.io/badge/tests-pytest-0A9EDC?logo=pytest&logoColor=white" alt="pytest">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
</p>

---

## 📖 Overview

Falls are the leading cause of injury for adults over 65, and the damage done is
driven less by the fall itself than by how long someone lies there before help
arrives. This system watches a room through an ordinary camera, recognises when a
person has gone down and stayed down, and pushes an alert to a carer — no wearable,
no button to press, no subscription hardware.

It is built to be **tuned and trusted** rather than treated as a black box: the
decision logic is plain Python with named thresholds, so you can replay a scenario
and see exactly why it did or did not alert.

## ✨ Features

- 🎯 **Two-signal fall detection** — posture shape *and* persistence must agree before an alert fires
- 🧠 **Bend-vs-fall discrimination** — tying a shoelace goes horizontal too; a confirmation window filters it out
- ⚡ **Velocity corroboration** — a sharp downward move halves the confirmation window, so real falls alert faster
- 🌗 **Lighting-tolerant** — MOG2 background subtraction adapts to curtains, dusk and slow light drift
- 👻 **Shadow rejection** — shadow pixels are thresholded away before they stretch the box sideways and fake a fall
- 📡 **Pluggable alerting** — console, webhook (n8n/Slack/dashboard) and Twilio SMS, all fanned out at once
- 🔕 **Cooldown control** — one incident produces one alert, not a pager storm
- 🛡️ **Fail-soft delivery** — if SMS is down, the webhook still fires and the monitor keeps watching
- 🧪 **Unit-tested decision logic** — no camera or video file needed to verify behaviour

## 🏗️ Architecture

```
📹 Camera / RTSP / video file
        │
        ▼
┌───────────────────────┐
│  FrameAnalyzer  🔍    │   MOG2 background subtraction → shadow removal →
│  (OpenCV half)        │   morphology → largest contour → bounding box
└───────────┬───────────┘
            │  bbox (x, y, w, h)
            ▼
┌───────────────────────┐
│  PostureTracker  🧠   │   aspect ratio → posture
│  (pure Python)        │   + streak length → persistence
└───────────┬───────────┘   + centroid velocity → corroboration
            │  FallEvent
            ▼
┌───────────────────────┐
│  AlertDispatcher  📡  │   cooldown → fan-out → best-effort delivery
└───────────┬───────────┘
            ▼
   💬 Console   🔗 Webhook   📱 SMS
```

The split between `FrameAnalyzer` and `PostureTracker` is deliberate. Vision code
needs a camera to exercise; decision code needs only numbers. Keeping them apart is
what makes the thresholds tunable with confidence.

### 🧭 How a fall is actually decided

| Signal | What it measures | Why it alone is not enough |
|---|---|---|
| 📐 **Aspect ratio** | Box wider than tall ⇒ horizontal | Bending, crouching and sitting on the floor all look horizontal |
| ⏱️ **Persistence** | Horizontal held for *N* frames | Someone resting on the floor deliberately would eventually trip it |
| 📉 **Drop velocity** | Normalised centroid fall per frame | Fast motion also occurs when walking toward the camera |

An alert requires shape **and** persistence. Velocity does not trigger on its own —
it acts as corroboration that shortens the wait, because a real fall arrives fast
while lowering yourself to the floor does not.

## 🚀 Quick Start

```bash
# 1️⃣ Clone and enter
git clone https://github.com/mueedmbrk/elder-care-monitoring-system.git
cd elder-care-monitoring-system

# 2️⃣ Set up an isolated environment
python3 -m venv .venv && source .venv/bin/activate

# 3️⃣ Install dependencies
pip install -r requirements.txt

# 4️⃣ Configure
cp .env.example .env        # then edit .env

# 5️⃣ Run against your webcam
python -m src.monitor
```

### 🎛️ CLI options

```bash
python -m src.monitor --source 0                  # webcam index
python -m src.monitor --source clip.mp4           # a recorded file
python -m src.monitor --source rtsp://cam/stream  # an IP camera
python -m src.monitor --headless                  # no preview window (servers, Raspberry Pi)
python -m src.monitor --verbose                   # debug logging
```

Press **`q`** to quit the preview window.

## ⚙️ Configuration

Every threshold lives in `.env` — nothing is hard-coded in the detector.

| Variable | Default | What it controls |
|---|---|---|
| `CAMERA_SOURCE` | `0` | Webcam index, file path or RTSP URL |
| `FALL_ASPECT_RATIO` | `1.25` | Width/height above which the silhouette reads as horizontal |
| `FALL_CONFIRM_FRAMES` | `18` | Frames the posture must hold before confirming |
| `MIN_CONTOUR_AREA` | `2500` | Blobs smaller than this are ignored (pets, curtains) |
| `DROP_VELOCITY` | `0.045` | Normalised centroid drop per frame that counts as corroboration |
| `ALERT_COOLDOWN_SECONDS` | `120` | Minimum gap between alerts |
| `ALERT_WEBHOOK_URL` | — | POST target for n8n / Slack / dashboards |
| `TWILIO_*`, `CARER_PHONE_NUMBER` | — | SMS channel; omit to disable it |

### 🎚️ Tuning guide

| Symptom | Adjust |
|---|---|
| 🔔 Alerts when someone bends down | ⬆️ raise `FALL_CONFIRM_FRAMES` |
| 😴 Real falls confirmed too slowly | ⬇️ lower `FALL_CONFIRM_FRAMES`, or ⬇️ lower `DROP_VELOCITY` |
| 🐕 A pet triggers detection | ⬆️ raise `MIN_CONTOUR_AREA` |
| 🪑 Furniture reads as a person | ⬆️ raise `MIN_CONTOUR_AREA`, reframe the camera |
| 🙇 Sitting on the floor alerts | ⬆️ raise `FALL_ASPECT_RATIO` |

## 🧪 Testing

```bash
pytest -v
```

The suite drives `PostureTracker` with synthetic bounding-box sequences — standing,
falling, bending, recovering, disappearing — so the alerting rules are verified
without a camera, a video fixture or an OpenCV install.

## 📁 Project Structure

```
elder-care-monitoring-system/
├── src/
│   ├── config.py       ⚙️  Environment-backed settings
│   ├── detector.py     🧠  PostureTracker (pure) + FrameAnalyzer (OpenCV)
│   ├── alerts.py       📡  Channels, fan-out and cooldown
│   └── monitor.py      ▶️  Capture loop, drawing and CLI entrypoint
├── tests/
│   ├── test_detector.py
│   └── test_alerts.py
├── .env.example
├── requirements.txt
└── README.md
```

## 🔐 Privacy Notes

Video is processed **frame by frame in memory** and never written to disk by this
code — only the alert text leaves the machine. Deployments in a real care setting
should still confirm consent with the resident and their family, and keep the camera
out of bathrooms and bedrooms unless that has been explicitly agreed.

## 🗺️ Roadmap

- [ ] 🦴 Pose-estimation backend (MediaPipe / YOLO-Pose) as an alternative to background subtraction
- [ ] 👥 Multi-person tracking with per-subject state
- [ ] 🎞️ Short pre/post-incident clip attached to the alert
- [ ] 📊 Web dashboard with incident history
- [ ] 🍓 Raspberry Pi deployment guide with a systemd unit

## ⚠️ Disclaimer

This is assistive monitoring software, not a certified medical device. It should
supplement human care and emergency procedures, never replace them.

## 📄 License

Released under the [MIT License](LICENSE).

## 👤 Author

**Mueed Mubarak** — AI Automation Engineer · Machine Learning Developer

[![Portfolio](https://img.shields.io/badge/Portfolio-mueedmbrk.github.io-22d3ee)](https://mueedmbrk.github.io/mueedmbrk/)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-mueed--mubarak-0A66C2?logo=linkedin&logoColor=white)](https://www.linkedin.com/in/mueed-mubarak/)
[![Email](https://img.shields.io/badge/Email-mueedmbrk%40gmail.com-EA4335?logo=gmail&logoColor=white)](mailto:mueedmbrk@gmail.com)

<p align="center">⭐ If this project is useful to you, a star is very welcome!</p>
