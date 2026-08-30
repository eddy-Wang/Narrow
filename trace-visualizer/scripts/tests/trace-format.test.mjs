import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseTrace } from '../../lib/trace.ts';

const legacy = JSON.stringify({
  run: { id: 'fixture', model: 'local', workers: 1, sampleCount: 2,
    hitRate: 0, mrr: 0, technicalScore: 0, diagnosisCounts: { unknown: 2 } },
  sessions: ['A', 'B'].map(sampleId => ({
    sampleId, scenario: 'buying', hit: false, firstHitTurn: null, bestRank: null,
    diagnosis: 'unknown', diagnosisReason: 'Snapshot missing',
    target: { parentAsin: sampleId, title: 'Target', category: '', price: null, rating: null },
    turns: [{ turn: 1, userMessage: 'Hello', semanticQuery: '', constraints: [],
      evaluationActive: true, relaxed: false, latencyMs: 1, diagnosis: 'unknown', reason: 'Snapshot missing',
      stages: ['lexical', 'dense', 'attribute', 'fusion', 'filter', 'rerank', 'response'].map(name => ({
        name, label: name, count: null, targetRank: null, status: 'unknown', signal: null,
      })) }],
  })),
});
test('reads existing legacy diagnostics', () => {
  assert.ok(parseTrace(legacy).sessions.length > 0);
});
test('reads v1 and BOM without changing trace data', () => {
  const data = JSON.parse(legacy);
  data.schema = 'shopping-agent.trace'; data.schemaVersion = 1;
  assert.deepEqual(parseTrace('\uFEFF' + JSON.stringify(data)), data);
});
test('rejects summary-only, malformed JSON, and unsupported versions', () => {
  assert.throws(() => parseTrace('{'), /JSON/);
  assert.throws(() => parseTrace('{"sample_count":200}'), /trace.json/);
  assert.throws(() => parseTrace('{"schema":"shopping-agent.trace","schemaVersion":2}'), /版本/);
});
test('rejects invalid nested stages instead of crashing the viewer', () => {
  const data = JSON.parse(legacy);
  data.sessions[0].turns[0].stages = [];
  assert.throws(() => parseTrace(JSON.stringify(data)), /排序阶段/);
});
test('rejects duplicate session identifiers and inconsistent counts', () => {
  const data = JSON.parse(legacy);
  data.sessions[1].sampleId = data.sessions[0].sampleId;
  assert.throws(() => parseTrace(JSON.stringify(data)), /重复/);
  data.run.sampleCount = 0;
  assert.throws(() => parseTrace(JSON.stringify(data)), /数量/);
});
