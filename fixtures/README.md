# Wire fixtures

`golden_frames.json` contains two factual external checksum vectors credited to
pybalboa tests/test_utils.py at the revision in docs/protocol_sources.md.
They are not captures from this project's spa.

The synthetic normal status fixture lives in
`tools/simulator/fixtures/normal.json` so it ships in installed wheels as well as
working from the checkout. Keep a single canonical copy. Generated CRCs on that
fixture are checked against the external vectors and independent checksum review.
