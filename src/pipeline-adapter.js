import { assertPipelineSnapshotConformance, definePipelineSnapshot, pipelineControlIntent } from "/commons/@inator/engine/pipeline-contract.js";

const emptySnapshot = Object.freeze({
  schema: "inator.pipeline-snapshot.v1",
  id: "bookinator-current-run",
  runId: "bookinator-current-run",
  revision: 0,
  state: "stopped",
  projects: [],
  units: [],
  progress: {completed: 0, total: 0, basis: "No pipeline snapshot has arrived yet.", referenceAt: null},
  controls: {},
  completion: {machine: "incomplete", review: "product-owned"}
});

export function createBookinatorPipelineSnapshot({pipeline = {}} = {}) {
  const snapshot = definePipelineSnapshot(pipeline.snapshot || emptySnapshot);
  assertPipelineSnapshotConformance(snapshot);
  return snapshot;
}

export function createBookinatorPipelineControlIntent({action, unitIds = [], snapshot} = {}) {
  return pipelineControlIntent({action, unitIds, expectedRevision: snapshot?.revision});
}
