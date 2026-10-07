require('dotenv').config();
const { createClient } = require('redis');
const { Pool } = require('pg');

const QUEUE_NAME = 'vote_queue';
const INSERT_VOTE_SQL = 'INSERT INTO vote (user_id, poll_id, choice) VALUES ($1, $2, $3)';

// One JSON object per line, matching app/entrypoint.sh and the Flask app, so
// `docker compose logs worker` can be grepped or shipped as-is.
function log(level, msg, fields = {}) {
    const entry = JSON.stringify({
        time: new Date().toISOString(),
        level,
        logger: 'voting.worker',
        msg,
        ...fields,
    });
    (level === 'ERROR' ? process.stderr : process.stdout).write(entry + '\n');
}

// Never let the database password reach the logs.
function redactUrl(raw) {
    try {
        const url = new URL(raw);
        if (url.password) url.password = '***';
        return url.toString();
    } catch (error) {
        return 'unparseable';
    }
}

/**
 * Pop one item off the queue and persist it. Never throws for application
 * outcomes — the status tells the caller what happened:
 *   saved     vote inserted
 *   duplicate unique constraint hit (user already voted) — skipped
 *   invalid   malformed JSON — discarded
 *   failed    any other insert error (result.error carries it)
 * A rejection from brPop itself (Redis down) DOES propagate; runLoop logs it
 * and retries.
 */
async function handleQueueItem(redisClient, pool, queue = QUEUE_NAME) {
    const item = await redisClient.brPop(queue, 0);
    let voteData;
    try {
        voteData = JSON.parse(item.element);
    } catch (error) {
        return { status: 'invalid', error };
    }
    try {
        await pool.query(INSERT_VOTE_SQL, [voteData.user_id, voteData.poll_id, voteData.choice]);
        return { status: 'saved', voteData };
    } catch (error) {
        return {
            status: error.code === '23505' ? 'duplicate' : 'failed',
            voteData,
            error,
        };
    }
}

async function runLoop(redisClient, pool, queue = QUEUE_NAME) {
    for (;;) {
        let result;
        try {
            result = await handleQueueItem(redisClient, pool, queue);
        } catch (error) {
            // Redis unreachable: log and retry rather than crash-restarting.
            log('ERROR', 'queue read failed', { queue, error: error.message });
            continue;
        }

        const { status, voteData, error } = result;
        if (status === 'saved') {
            log('INFO', 'vote saved to database', {
                user_id: voteData.user_id,
                poll_id: voteData.poll_id,
                choice: voteData.choice,
            });
        } else if (status === 'duplicate') {
            log('WARN', 'duplicate vote skipped', {
                user_id: voteData.user_id,
                poll_id: voteData.poll_id,
            });
        } else if (status === 'invalid') {
            log('WARN', 'malformed queue item discarded', { queue });
        } else {
            log('ERROR', 'vote insert failed', {
                user_id: voteData && voteData.user_id,
                error: error.message,
            });
        }
    }
}

async function startWorker() {
    const pool = new Pool({ connectionString: process.env.DATABASE_URL });
    const redisClient = createClient({ url: process.env.REDIS_URL });
    redisClient.on('error', (err) => log('ERROR', 'redis client error', { error: err.message }));

    await redisClient.connect();
    log('INFO', 'worker connected, listening for votes', {
        queue: QUEUE_NAME,
        pid: process.pid,
        database: redactUrl(process.env.DATABASE_URL),
        redis: process.env.REDIS_URL,
    });
    await runLoop(redisClient, pool, QUEUE_NAME);
}

if (require.main === module) {
    startWorker().catch((error) => {
        log('ERROR', 'worker failed to start', { error: error.message });
        process.exit(1);
    });
}

module.exports = { QUEUE_NAME, INSERT_VOTE_SQL, handleQueueItem, runLoop, startWorker };
