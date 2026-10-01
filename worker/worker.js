require('dotenv').config();
const { createClient } = require('redis');
const { Pool } = require('pg');

// Connect to PostgreSQL
const pool = new Pool({
    connectionString: process.env.DATABASE_URL,
});

// Connect to Redis
const redisClient = createClient({
    url: process.env.REDIS_URL
});

redisClient.on('error', (err) => console.log('Redis Client Error', err));

async function startWorker() {
    await redisClient.connect();
    console.log('✅ Node.js Worker connected to Redis and PostgreSQL');
    console.log('👀 Listening for votes on the "vote_queue"...');

    while (true) {
        try {
            // BRPOP blocks until an item is available in the list
            const vote = await redisClient.brPop('vote_queue', 0);
            const voteData = JSON.parse(vote.element);
            
            console.log(`Processing vote: User ${voteData.user_id} voted for ${voteData.choice}`);

            // Insert into PostgreSQL
            const query = 'INSERT INTO vote (user_id, poll_id, choice) VALUES ($1, $2, $3)';
            await pool.query(query, [voteData.user_id, voteData.poll_id, voteData.choice]);
            
            console.log(`✅ Successfully saved vote to database for User ${voteData.user_id}`);
        } catch (error) {
            // Catch unique constraint violation (if user somehow double votes)
            if (error.code === '23505') {
                console.error('❌ Duplicate vote detected for this user. Skipping.');
            } else {
                console.error('❌ Error processing vote:', error.message);
            }
        }
    }
}

startWorker();
