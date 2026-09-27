# BlackMamba Automator queue bridge

WARPBLACK can now consume the canonical job/result envelopes emitted by
BlackMamba Automator without exposing a generic shell path.

## Run one job

    warpblack-automator \
      --queue ~/.blackmamba-automator/warpblack \
      --workspace ~/Projects \
      --once

## Watch continuously

    warpblack-automator \
      --queue ~/.blackmamba-automator/warpblack \
      --workspace ~/Projects \
      --watch

The first executable adapter is workspace/import_project_reference. It verifies
that the discovered project exists inside the configured workspace root and then
registers it using WARPBLACK's existing ProjectRegistry.

High-risk, irreversible, or authorization-gated Automator jobs are blocked by
this worker. There is deliberately no argv or arbitrary shell field in this
protocol.

The round trip is:

    Automator detector
      -> JobEnvelope
      -> WARPBLACK automator queue
      -> allowlisted adapter
      -> validator
      -> ResultEnvelope
      -> Automator ledger/evidence
