# Hyperframes Composition Brief: UTGPT

## Objective
Create a polished launch-style brag video for UTGPT, the on-device AI chat application for Ubuntu Touch.

## Output
- Composition directory: `brag-output/composition/`
- Rendered video: `brag-output/brag.mp4`
- Format: landscape — 1920x1080
- Duration: 20 seconds

## Source Material
- Project root: `/home/suraj/utgpt`
- Primary files read: `README.md`, `qml/Main.qml`, `qml/pages/ChatPage.qml`, `qml/pages/SettingsPage.qml`, `assets/logo.png`, `clickable.yaml`
- Product name: UTGPT
- Tagline / strongest claim: "On-device AI chat built specifically for Ubuntu Touch — run lightweight LLMs directly on your mobile device."
- Key UI or visual moment to recreate:
  - Lomiri dark maroon theme (#5C0A1A, #121212, #1E1E1E)
  - Local GGUF model cards (Qwen2.5, SmolLM2, TinyLlama)
  - Hardware performance sliders (CPU threads, context size, Flash Attention)
  - Real-time chat streaming with thinking state indicator
  - UTGPT logo and Ubuntu Touch branding
- Copy that must appear verbatim:
  - "Who said your phone needs the cloud for AI?"
  - "UTGPT: On-Device AI for Ubuntu Touch"
  - "100% Offline. Zero Telemetry. Complete Privacy."

## Creative Direction
- Tone preset: polished
- Creative direction: Sleek mobile AI launch video for Ubuntu Touch
- Interpretation: Technical sophistication, high-contrast dark UI with wine/maroon accents, smooth transitions, legible typographic hierarchy, and deliberate pacing.
- Angle: Emphasize local mobile sovereignty. No servers, no tracking, pure offline LLM inference directly on mobile hardware.
- Hook: "Who said your phone needs the cloud for AI?"
- Outro / punchline: "Zero servers. Zero telemetry. Pure on-device intelligence."
- Avoid:
  - Generic SaaS language
  - Abstract filler visuals
  - Low-contrast unreadable text
  - Overly hectic motion

## Visual Identity
- Background: #121212 (Dark slate) with subtle radial gradient (#3D141C / #5C0A1A)
- Card / Panel: #1E1E1E
- Card Border: #2D2D2D
- Primary Text: #F8FAFC
- Secondary / Muted Text: #94A3B8
- Accent / Brand: #FF8093 and #5C0A1A (Ubuntu Touch Maroon)
- Display font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Ubuntu", sans-serif
- Body font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Ubuntu", sans-serif
- Visual references from the project: `assets/logo.png`, `qml/Main.qml` styling constants

## Storyboard
Use the storyboard in `brag-output/brag-plan.md` as the creative contract:
1. The Hook (0.0s - 3.5s) — Bold statement: "Who said your phone needs the cloud for AI?" + UTGPT intro badge.
2. Local Model Freedom (3.5s - 8.0s) — GGUF model cards (Qwen2.5, SmolLM2, TinyLlama) with instant selection.
3. Hardware Tuning (8.0s - 12.5s) — Performance controls: CPU Threads (4), Context Limit (2048), Flash Attention (Enabled).
4. Real-Time Chat (12.5s - 17.0s) — Simulated mobile chat interface: user prompt, animated thinking dots, streaming tokens.
5. Outro / Punchline (17.0s - 20.0s) — "100% Offline. Zero Telemetry. Complete Privacy." + UTGPT logo and Ubuntu Touch branding.

## Audio
- Audio role: Technical groove with crisp UI clicks and resonant outro bell.
- Audio arc: Confident entrance, steady rhythmic development across feature cards, gentle ducking during chat stream, impactful final chord.
- Music: `assets/music/happy-beats-business-moves-vol-12-by-ende-dot-app.mp3`
- Music treatment: Volume 0.32, fade-out from 18.5s to 20.0s.
- Music cue guidance: Target strong cues at 8.74s, 13.11s, 17.47s.
- Audio-reactive treatment: Subtle; background ambient radial gradient warmth and card borders breathe with music RMS.
- SFX selection:
  - `assets/sfx/interface/drop_001.ogg` for intro badge entrance.
  - `assets/sfx/interface/select_008.ogg` for model selection.
  - `assets/sfx/interface/switch_001.ogg` for hardware toggle.
  - `assets/sfx/impact/impactBell_heavy_000.ogg` for outro logo settle.
  - `assets/sfx/impact/impactSoft_medium_000.ogg` for transition impact.

## Hyperframes Instructions
Requirements:
- Show real UI components, copy, and architecture from UTGPT.
- Keep all text readable with strong WCAG contrast.
- Total duration: 20.0 seconds.
- Copy music and SFX into `brag-output/composition/assets/`.
- Validate with `npx hyperframes check` before rendering.
