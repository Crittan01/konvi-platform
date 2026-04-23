const { createClient } = require('@supabase/supabase-js');
const fs = require('fs');

async function test() {
    const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL || "http://127.0.0.1:54321";
    const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    if (!SUPABASE_ANON_KEY) throw new Error("No anon key");

    const client = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
    
    // We need a valid JWT for a user. Let's login exactly like the frontend.
    const { data: authData, error: authErr } = await client.auth.signInWithPassword({
        email: "c.garzon@commerceops.test", // Let's check test DB for a user
        password: "password123" // assuming default test pass
    });
    
    if (authErr && authErr.message.includes("Invalid login")) {
        console.log("Cannot login. Checking DB users...");
        return;
    }
    console.log("Logged in:", authData?.user?.id);
    
    // Subscribe to messages
    const channel = client.channel('test-messages')
        .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'messages' }, payload => {
            console.log("REALTIME RECEIVED:", payload);
        })
        .subscribe((status) => {
            console.log("Subscription status:", status);
        });

    setTimeout(() => {
        console.log("Exiting...");
        process.exit(0);
    }, 5000);
}
test().catch(console.error);
