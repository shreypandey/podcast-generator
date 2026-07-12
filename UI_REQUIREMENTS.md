# UI Requirements

Requirements for M5: the frontend that turns the backend podcast generator into a usable product.

## Goal

The UI should let a user create, steer, monitor, listen to, inspect, and iterate on podcast runs without touching backend artifacts or logs.

The first screen should be the actual podcast generator, not a marketing landing page.

## Primary User Flow

1. User enters a topic and optional sources.
2. User chooses generation settings.
3. User starts a run.
4. UI streams progress stage by stage.
5. When outputs are ready, user can listen, read transcript, inspect sources, and review citations.
6. User can adjust steering and regenerate.

## Run Creation

The creation form must include:

- Topic input.
- Optional source inputs:
  - URL list.
  - Text/Markdown paste.
  - PDF upload once backend support exists.
- Research mode:
  - Live web research.
  - Use only my sources.
  - Hybrid.
- Length:
  - Short.
  - Medium.
  - Long.
- Depth:
  - 1 to 5.
- Languages:
  - `en-IN`.
  - `hi-IN`.
  - `bn-IN`.
  - `ta-IN`.
  - `te-IN`.
  - `mr-IN`.
  - `gu-IN`.
  - `kn-IN`.
  - `ml-IN`.
  - `pa-IN`.
  - `od-IN`.

## Steering Controls

Content steering:

- Angle preset:
  - Balanced.
  - Mechanism.
  - Current.
  - Controversy.
  - Practical.
  - Myth-busting.
  - Beginner.
- Focus questions:
  - Add up to 5.
  - Show character limits.
  - Allow reorder/delete.
- Custom angle text.

Delivery steering:

- Tone preset:
  - Conversational.
  - Serious.
  - Energetic.
  - Calm.
  - Investigative.
- Style preset:
  - Curious expert.
  - Debate.
  - Storytelling.
  - Classroom.
  - News analysis.
- Custom style text.

The UI should make clear that grounding, citations, and role boundaries override style instructions.

## Live Progress

The run page must show:

- Current status:
  - Queued.
  - Running.
  - Succeeded.
  - Failed.
  - Canceled.
- Current stage:
  - Query planning.
  - Research.
  - Grounding.
  - Annotation.
  - Casting.
  - Planning.
  - Dialogue.
  - Verification.
  - Review.
  - Humanize.
  - Render.
  - Citations.
  - Complete.
- Progress count and label from the API.
- Event stream log with user-safe messages.
- Cancel button while run is active.
- Retry/regenerate action after failure.

## Results Page

The completed run page must include:

- Episode title/topic.
- Run settings summary.
- Cast summary:
  - Host name.
  - Expert name.
  - Voices.
- Language selector.
- Audio player for selected language.
- Duration and readiness per language.
- Transcript tab.
- Sources tab.
- Facts/evidence tab.
- Debug/artifacts tab.

## Audio Player

The player should support:

- Play/pause.
- Seek.
- Current time and duration.
- Language selection.
- Download link if backend supports it.
- Clear loading/error states when an audio file is not ready.

Future:

- Transcript highlighting by current playback time once timestamps exist.

## Transcript View

Transcript must show:

- Speaker name.
- Speaker role.
- Turn text/spoken delivery for selected language.
- Citation numbers on cited expert turns.
- Verification status.
- Warning marker for unverified or accepted-and-flagged turns.

Interactions:

- Clicking a citation opens the source detail.
- Clicking a turn shows cited facts and source quotes.
- Filter to show only cited turns.
- Filter to show unverified/flagged turns.

## Source Explorer

Sources tab must show:

- Source number.
- Source title.
- URL.
- Origin:
  - Exa.
  - User source.
- Query IDs.
- Query intents.
- Search rank.
- Snippet/highlights.
- Linked fact IDs.

Interactions:

- Open source URL.
- Filter by query intent.
- Filter by used/unused in final script.
- Show all facts extracted from a source.

## Facts And Evidence View

This is important for trust and debugging.

Show:

- Fact ID.
- Claim.
- Fact type.
- Story role.
- Quality score.
- Quality notes.
- Evidence strength.
- Caveats.
- Conflicts with.
- Source IDs.
- Source quotes.
- Whether used in outline/script.

Filters:

- Used in final script.
- Unused.
- Caveat/counterclaim.
- Misconception.
- High quality.
- Weak evidence.

## Artifact And Debug View

For development builds, expose:

- `brief`.
- `query_plan`.
- `source`.
- `factsheet`.
- `cast`.
- `outline`.
- `script`.
- `manifest`.

This can be hidden behind an "Advanced" or "Debug" tab.

## Metrics Panel

Show a compact scorecard:

- Sources found.
- Sources grounded.
- Final facts.
- Facts used.
- Grounding rate.
- Unverified turns.
- Challenge count.
- Render duration.
- Episode duration per language.
- Translation fidelity once implemented.
- Total latency.

## Run History

Users need to return to prior outputs.

Show:

- Recent runs.
- Topic.
- Status.
- Created time.
- Languages.
- Length/depth.
- Steering summary.
- Quick open/delete once delete is supported.

## Error And Empty States

Required states:

- No runs yet.
- Run queued.
- Run in progress.
- Audio not ready.
- Transcript not ready.
- Sources not ready.
- Run failed.
- Run canceled.
- Partial language render failure.
- API unavailable.

Error messages should be specific enough to act on, but should not dump raw backend traces by default.

## Design Direction

This is an operational research/listening tool, not a marketing site.

The UI should be:

- Dense but readable.
- Source-forward.
- Calm and utilitarian.
- Optimized for scanning and comparison.
- Clear about what is verified vs flagged.
- Built around the generated episode, not decorative cards.

Avoid:

- A landing-page hero as the main experience.
- Decorative gradients/orbs.
- Overly large marketing typography.
- Hiding evidence behind vague summaries.

## API Dependencies

Current backend endpoints expected by the UI:

- `POST /api/runs`
- `GET /api/runs`
- `GET /api/runs/{run_id}`
- `POST /api/runs/{run_id}/cancel`
- `GET /api/runs/{run_id}/events`
- `GET /api/runs/{run_id}/audio?lang=...`
- `GET /api/runs/{run_id}/transcript?lang=...`
- `GET /api/runs/{run_id}/sources`
- `GET /api/runs/{run_id}/episode?lang=...`
- `GET /api/runs/{run_id}/manifest`
- `GET /api/runs/{run_id}/artifacts/{name}`

Backend gaps that the UI will eventually need:

- Source upload endpoints.
- User-source-only mode.
- Regenerate segment/run endpoint.
- Delete run endpoint.
- Audio timestamps.
- Translation fidelity fields.
- More explicit quality metrics in run detail.

## M5 Acceptance Criteria

M5 is usable when:

- A user can create a podcast run from the browser.
- Steering controls map to the backend request.
- Live progress updates without refreshing.
- Completed audio can be played in every ready language.
- Transcript citations link to source details.
- Sources and extracted facts can be inspected.
- Failed runs show useful errors.
- Run history works.
- The UI exposes enough evidence to trust or challenge the generated episode.
