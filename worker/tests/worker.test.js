// Unit tests for the worker's queue-processing path. Run with `npm test`
// (node's built-in runner — no test framework dependency).
//
// The Redis client and the pg pool are both fakes: these tests prove the
// processing logic and its error mapping, while scripts/e2e-test.* prove the
// real worker drains the real queue against real services.
const { test } = require('node:test');
const assert = require('node:assert/strict');

const { QUEUE_NAME, INSERT_VOTE_SQL, handleQueueItem } = require('../worker.js');

function fakeRedis(payload) {
    const calls = [];
    return {
        calls,
        async brPop(queue, timeout) {
            calls.push({ queue, timeout });
            if (payload instanceof Error) throw payload;
            return { element: payload };
        },
    };
}

function fakePool(error) {
    const calls = [];
    return {
        calls,
        async query(sql, params) {
            calls.push({ sql, params });
            if (error) throw error;
            return { rowCount: 1 };
        },
    };
}

const VALID_VOTE = JSON.stringify({ user_id: 7, poll_id: 1, choice: 'A' });

test('saves a valid vote and reports saved', async () => {
    const redis = fakeRedis(VALID_VOTE);
    const pool = fakePool();

    const result = await handleQueueItem(redis, pool);

    assert.equal(result.status, 'saved');
    assert.deepEqual(result.voteData, { user_id: 7, poll_id: 1, choice: 'A' });
    assert.deepEqual(redis.calls, [{ queue: QUEUE_NAME, timeout: 0 }]);
    assert.equal(pool.calls.length, 1);
    assert.equal(pool.calls[0].sql, INSERT_VOTE_SQL);
    assert.deepEqual(pool.calls[0].params, [7, 1, 'A']);
});

test('blocks on the configured queue with an infinite timeout', async () => {
    const redis = fakeRedis(VALID_VOTE);
    await handleQueueItem(redis, fakePool(), 'custom_queue');
    assert.deepEqual(redis.calls, [{ queue: 'custom_queue', timeout: 0 }]);
});

test('maps unique-constraint violations to duplicate', async () => {
    const duplicate = Object.assign(new Error('duplicate key value'), { code: '23505' });
    const result = await handleQueueItem(fakeRedis(VALID_VOTE), fakePool(duplicate));

    assert.equal(result.status, 'duplicate');
    assert.equal(result.error.code, '23505');
    assert.equal(result.voteData.user_id, 7);
});

test('maps other insert errors to failed and keeps the error', async () => {
    const down = Object.assign(new Error('connection terminated'), { code: 'ECONNREFUSED' });
    const result = await handleQueueItem(fakeRedis(VALID_VOTE), fakePool(down));

    assert.equal(result.status, 'failed');
    assert.equal(result.error.message, 'connection terminated');
});

test('discards malformed JSON without touching the database', async () => {
    const pool = fakePool();
    const result = await handleQueueItem(fakeRedis('not-json{'), pool);

    assert.equal(result.status, 'invalid');
    assert.equal(pool.calls.length, 0);
});

test('propagates Redis outages so runLoop can log and retry', async () => {
    const outage = Object.assign(new Error('connect ECONNREFUSED'), { code: 'ECONNREFUSED' });
    await assert.rejects(() => handleQueueItem(fakeRedis(outage), fakePool()), {
        message: 'connect ECONNREFUSED',
    });
});
